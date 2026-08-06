import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import get_encryptor
from app.core.logging import logger
from app.models.analysis_result import AnalysisResult
from app.schemas.analysis import AnalysisGuideResponse, QuickCheckFinding
from app.services.drug_service import DrugService
from app.services.ollama_client import OllamaClient, OllamaUnavailableError
from app.services.user_service import UserService

_MAX_FIELD_CHARS = 800  # 프롬프트 길이 방어 — 공공데이터 텍스트가 길 수 있어 필드당 상한

_FALLBACK_GUIDE_TEXT = (
    "지금 AI 설명을 생성할 수 없습니다. 위 판정 결과(병용금기/효능군중복)는 "
    "식약처 공공데이터에 근거해 이미 확정된 것이니 그대로 참고하시고, "
    "자세한 대응은 의사·약사와 상담해 주세요."
)

_SYSTEM_PROMPT = """당신은 의약품 병용 위험을 설명하는 보조 도우미입니다.
아래 원칙을 반드시 지키세요:
1. 오직 사용자가 제공한 [판정 결과]와 [약품 정보] 안의 내용만 근거로 설명하세요.
   그 안에 없는 사실(예: 언급되지 않은 부작용, 성분, 기전)을 추측하거나 지어내지 마세요.
2. 이 판정은 이미 식약처 공공데이터(DUR)를 직접 조회해 확정된 결과입니다.
   당신은 이 판정을 바꾸거나 재평가하지 말고, 그대로 받아들여 쉽게 풀어 설명만 하세요.
3. 이것은 의학적 진단이 아니라 참고용 AI 설명("첨언")입니다. 위험 등급이 critical이면
   반드시 "의사·약사와 상담하세요"를 포함해 안내하세요.
4. 한국어로, 일반인이 이해하기 쉽게 간결히 답하세요."""


class AiGuideService:
    """규칙 기반 판정(AnalysisService.quick_check)이 이미 확정한 결과를 사람이
    읽을 설명으로 풀어쓰는 보조 역할만 한다 — 위험도 판정 자체에는 관여하지 않는다.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._enc = get_encryptor()
        self._ollama = OllamaClient()

    async def generate_guide(
        self,
        user_id: uuid.UUID,
        drug_ids: list[uuid.UUID],
        findings: list[QuickCheckFinding],
        risk_level: str,
    ) -> AnalysisGuideResponse:
        prompt = await self._build_prompt(user_id, findings, risk_level)

        is_ai_generated = True
        try:
            guide_text = await self._ollama.generate(prompt, system=_SYSTEM_PROMPT)
        except OllamaUnavailableError:
            logger.warning("Ollama 가이드 생성 실패 — 폴백 문구로 대체 (판정 결과는 영향 없음)")
            guide_text = _FALLBACK_GUIDE_TEXT
            is_ai_generated = False

        await self._persist(user_id, drug_ids, findings, risk_level, guide_text)

        return AnalysisGuideResponse(
            risk_level=risk_level, guide_text=guide_text, is_ai_generated=is_ai_generated
        )

    async def _build_prompt(
        self, user_id: uuid.UUID, findings: list[QuickCheckFinding], risk_level: str
    ) -> str:
        drug_ids = {f.drug1_id for f in findings} | {f.drug2_id for f in findings}
        drugs = await DrugService(self.db).get_drugs_by_ids(list(drug_ids))

        findings_lines = []
        for f in findings:
            kind = "병용금기(절대 금기)" if f.interaction_type == "contraindicated" else "효능군중복(주의)"
            findings_lines.append(f"- {f.drug1_name} + {f.drug2_name}: {kind} — {f.mechanism or '정보 없음'}")

        drug_lines = []
        for drug in drugs.values():
            name = drug.simple_name or drug.item_name
            parts = [f"[{name}]"]
            if drug.efcy_qesitm:
                parts.append(f"효능: {drug.efcy_qesitm[:_MAX_FIELD_CHARS]}")
            if drug.atpn_qesitm:
                parts.append(f"주의사항: {drug.atpn_qesitm[:_MAX_FIELD_CHARS]}")
            if drug.se_qesitm:
                parts.append(f"부작용: {drug.se_qesitm[:_MAX_FIELD_CHARS]}")
            drug_lines.append(" / ".join(parts))

        # 사용자 건강정보/알레르기 — 복호화 실패는 UserService가 필드별로 격리 처리하므로
        # 여기서는 있으면 쓰고 없으면 그냥 생략한다 (가이드 생성 전체를 막지 않음).
        health_lines = []
        try:
            user = await UserService(self.db).get_user(user_id)
            if getattr(user, "health_conditions", None):
                health_lines.append(f"건강 상태: {', '.join(user.health_conditions)}")
            if getattr(user, "allergy_info", None):
                health_lines.append(f"알레르기: {', '.join(user.allergy_info)}")
        except Exception:
            logger.warning("사용자 건강정보 조회 실패 — 컨텍스트 없이 가이드 생성 진행", exc_info=True)

        sections = [
            f"[판정 결과] 위험 등급: {risk_level}",
            "\n".join(findings_lines) or "(구체적 병용 findings 없음)",
            "[약품 정보]",
            "\n".join(drug_lines) or "(약품 상세 정보 없음)",
        ]
        if health_lines:
            sections.append("[사용자 정보]\n" + "\n".join(health_lines))
        sections.append("위 정보만 근거로, 왜 위험한지와 어떻게 대응해야 하는지 설명해 주세요.")

        return "\n\n".join(sections)

    async def _persist(
        self,
        user_id: uuid.UUID,
        drug_ids: list[uuid.UUID],
        findings: list[QuickCheckFinding],
        risk_level: str,
        guide_text: str,
    ) -> None:
        result = AnalysisResult(
            user_id=user_id,
            drug_ids=[str(d) for d in drug_ids],
            findings_snapshot=[f.model_dump(mode="json") for f in findings],
            risk_level=risk_level,
            model_name=settings.OLLAMA_MODEL,
            action_guide_encrypted=self._enc.encrypt(guide_text),
        )
        self.db.add(result)
        await self.db.commit()
