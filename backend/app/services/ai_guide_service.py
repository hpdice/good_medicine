import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import get_encryptor
from app.core.logging import logger
from app.models.analysis_result import AnalysisResult
from app.schemas.analysis import AnalysisGuideResponse, QuickCheckResponse
from app.services.drug_service import DrugService
from app.services.ollama_client import OllamaClient, OllamaUnavailableError
from app.services.user_service import UserService

_MAX_FIELD_CHARS = 800  # 프롬프트 길이 방어 — 공공데이터 텍스트가 길 수 있어 필드당 상한
_MAX_ATTEMPTS = 2  # 검사에 걸린 답은 한 번만 다시 생성하고, 그래도 안 되면 폴백 문구

_FALLBACK_GUIDE_TEXT = (
    "지금 AI 설명을 생성할 수 없습니다. 위 판정 결과는 식약처 DUR 공공데이터와 "
    "등록하신 건강정보(알레르기·나이·임신 여부)에 근거해 이미 확정된 것이니 그대로 "
    "참고하시고, 자세한 대응은 의사·약사와 상담해 주세요."
)

# 내부 등급 코드(critical 등)를 프롬프트에 그대로 넣으면 모델이 "critical 등급"처럼
# 화면에 따라 쓴다(2026-10-15 실측) — 사용자에게 보이는 말로 바꿔서 넘긴다.
_RISK_LABEL = {"critical": "위험", "caution": "주의", "safe": "안전"}
_FINDING_LABEL = {
    "contraindicated": "병용금기(함께 먹으면 안 되는 조합)",
    "duplicate_ingredient": "동일 성분 중복(같은 성분을 겹쳐 먹게 됨)",
    "duplicate_effect_group": "효능군 중복(비슷한 작용의 약을 겹쳐 먹게 됨)",
}
_AGE_RULE_LABEL = {"age_taboo": "특정 연령대 금기", "elderly_caution": "노인 주의(만 65세 이상)"}

_SYSTEM_PROMPT = """당신은 의약품 병용 위험을 설명하는 보조 도우미입니다.
아래 원칙을 반드시 지키세요:
1. 오직 사용자가 제공한 [판정 결과]와 [약품 정보] 안의 내용만 근거로 설명하세요.
   그 안에 없는 증상, 장기, 기전, 확률을 덧붙이거나 지어내지 마세요.
2. 이 판정은 이미 식약처 공공데이터(DUR)와 사용자 건강정보로 확정된 결과입니다.
   판정을 바꾸거나 재평가하지 말고, 그대로 받아들여 쉽게 풀어 설명만 하세요.
3. 알레르기·나이·임신 항목은 약 한 가지에 대한 경고입니다. 두 약 사이의 상호작용처럼
   설명하지 마세요.
4. 복용을 스스로 중단하거나 바꾸라고 권하지 마세요. "임의로 복용을 중단하거나 바꾸지 말고
   의사·약사와 상담하세요"라는 취지로 마무리하세요.
5. 일반인이 이해하기 쉬운 한국어 문장 3~6개로, 문단은 2개 이하로 쓰세요.
   마크다운(**, #, 글머리 기호, 번호 목록), 영어 단어, 한자는 쓰지 마세요."""

_MARKDOWN_EMPHASIS = re.compile(r"\*\*|__")
_MARKDOWN_LINE_PREFIX = re.compile(r"^[ \t]*(?:#{1,6}|[-*•]|\d+[.)])[ \t]+", re.M)
_HAN_OR_KANA = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# \b는 한글도 단어 문자로 봐서 "critical인"을 못 잡는다 — 영문자 경계만 본다
_RISK_CODE = re.compile(r"(?<![A-Za-z])(?:critical|caution|safe)(?![A-Za-z])", re.I)
_STOP_WORD = re.compile(r"중단|끊")
_NEGATION_AFTER_STOP = re.compile(r"^[^.!?\n]{0,12}?(?:지\s*마|지\s*말|면\s*안)")


def sanitize_guide_text(text: str) -> str:
    """앱은 받은 문자열을 그대로 그리므로 마크다운 기호를 걷어낸다(내용은 유지)."""
    text = _MARKDOWN_EMPHASIS.sub("", text)
    text = _MARKDOWN_LINE_PREFIX.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def guide_text_problem(text: str) -> str | None:
    """사용자에게 내보내면 안 되는 답이면 그 이유를, 괜찮으면 None을 돌려준다.

    지시문만으로는 막히지 않는 것들(2026-10-15 실측: 23회 중 10회)을 결정론적으로 거른다.
    """
    if not text:
        return "빈 응답"
    if _HAN_OR_KANA.search(text):
        return "한자·가나 섞임"
    if _RISK_CODE.search(text):
        return "내부 등급 코드 노출"
    for m in _STOP_WORD.finditer(text):
        # "임의로 중단하지 마세요"처럼 말리는 문장은 허용하고, 끊으라는 권유만 막는다
        if not _NEGATION_AFTER_STOP.match(text[m.end():]):
            return "복용 중단 권유"
    return None


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
        check: QuickCheckResponse,
    ) -> AnalysisGuideResponse:
        prompt = await self._build_prompt(user_id, check)

        guide_text, is_ai_generated = _FALLBACK_GUIDE_TEXT, False
        try:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                candidate = sanitize_guide_text(await self._ollama.generate(prompt, system=_SYSTEM_PROMPT))
                problem = guide_text_problem(candidate)
                if problem is None:
                    guide_text, is_ai_generated = candidate, True
                    break
                logger.warning(f"AI 가이드 응답 검사 실패({problem}) — 시도 {attempt}/{_MAX_ATTEMPTS}")
            else:
                logger.warning("AI 가이드 재생성도 검사 실패 — 폴백 문구로 대체 (판정 결과는 영향 없음)")
        except OllamaUnavailableError:
            logger.warning("Ollama 가이드 생성 실패 — 폴백 문구로 대체 (판정 결과는 영향 없음)")

        await self._persist(user_id, drug_ids, check, guide_text)

        return AnalysisGuideResponse(
            risk_level=check.risk_level, guide_text=guide_text, is_ai_generated=is_ai_generated
        )

    async def _build_prompt(self, user_id: uuid.UUID, check: QuickCheckResponse) -> str:
        finding_lines = []
        for finding in check.findings:
            kind = _FINDING_LABEL.get(finding.interaction_type, "주의가 필요한 조합")
            tags = f" [주요 위험: {', '.join(finding.risk_tags)}]" if finding.risk_tags else ""
            finding_lines.append(
                f"- {finding.drug1_name} + {finding.drug2_name}: {kind} — {finding.mechanism or '정보 없음'}{tags}"
            )
        allergy_lines = [
            f"- {c.drug_name}: 등록한 알레르기 '{c.matched_allergy_term}'와 이 약의 성분 '{c.matched_ingredient}'이 겹침"
            for c in check.allergy_conflicts
        ]
        age_lines = [
            f"- {c.drug_name}: {_AGE_RULE_LABEL.get(c.rule_type, '연령 관련 주의')} — {c.prohibit_content or '정보 없음'}"
            for c in check.age_cautions
        ]
        pregnancy_lines = [
            f"- {c.drug_name}: 임부금기(임신 중 사용을 피해야 함) — {c.prohibit_content or '정보 없음'}"
            + (f" (적용 범위: {c.remark})" if c.remark else "")
            for c in check.pregnancy_cautions
        ]

        drug_ids = (
            {f.drug1_id for f in check.findings}
            | {f.drug2_id for f in check.findings}
            | {c.drug_id for c in check.allergy_conflicts}
            | {c.drug_id for c in check.age_cautions}
            | {c.drug_id for c in check.pregnancy_cautions}
        )
        drugs = await DrugService(self.db).get_drugs_by_ids(list(drug_ids))

        drug_lines = []
        for drug in drugs.values():
            name = drug.simple_name or drug.item_name
            parts = [f"[{name}]"]
            # e약은요 데이터가 없는 약(86%)은 이름만 남아 한국어 맥락이 짧아지는데, 그때
            # 모델이 첫 문장 뒤 중국어로 넘어갔다(임부금기 단독 5/5, 2026-10-15 실측).
            # 분류명에 마지막 줄 "한국어로만" 지시를 더하자 0/8로 사라졌다("한국어로만"만으로는 5/8).
            if drug.class_name:
                parts.append(f"분류: {drug.class_name}")
            if drug.efcy_qesitm:
                parts.append(f"효능: {drug.efcy_qesitm[:_MAX_FIELD_CHARS]}")
            if drug.atpn_qesitm:
                parts.append(f"주의사항: {drug.atpn_qesitm[:_MAX_FIELD_CHARS]}")
            if drug.intrc_qesitm:
                parts.append(f"상호작용: {drug.intrc_qesitm[:_MAX_FIELD_CHARS]}")
            if drug.se_qesitm:
                parts.append(f"부작용: {drug.se_qesitm[:_MAX_FIELD_CHARS]}")
            drug_lines.append(" / ".join(parts))

        # 사용자 건강정보/알레르기 — 복호화 실패는 UserService가 필드별로 격리 처리하므로
        # 여기서는 있으면 쓰고 없으면 그냥 생략한다 (가이드 생성 전체를 막지 않음).
        health_lines = []
        try:
            user = await UserService(self.db).get_user(user_id)
            conditions = getattr(user, "health_conditions", None)
            allergies = getattr(user, "allergy_info", None)
            if conditions:
                health_lines.append(f"건강 상태: {', '.join(conditions)}")
            if allergies:
                health_lines.append(f"알레르기: {', '.join(allergies)}")
        except Exception:
            logger.warning("사용자 건강정보 조회 실패 — 컨텍스트 없이 가이드 생성 진행", exc_info=True)

        sections = [f"[판정 결과] 전체 위험도: {_RISK_LABEL.get(check.risk_level, check.risk_level)}"]
        for title, lines in (
            ("함께 먹을 때의 문제", finding_lines),
            ("알레르기 성분 충돌", allergy_lines),
            ("나이 관련 DUR 규칙", age_lines),
            ("임신 중 금기", pregnancy_lines),
        ):
            if lines:
                sections.append(f"[{title}]\n" + "\n".join(lines))
        if len(sections) == 1:
            sections.append("(확인된 문제 없음)")
        sections.append("[약품 정보]\n" + ("\n".join(drug_lines) or "(약품 상세 정보 없음)"))
        if health_lines:
            sections.append("[사용자 정보]\n" + "\n".join(health_lines))
        sections.append("위 정보만 근거로, 왜 위험한지와 어떻게 대응해야 하는지 한국어로만 설명해 주세요.")

        return "\n\n".join(sections)

    async def _persist(
        self,
        user_id: uuid.UUID,
        drug_ids: list[uuid.UUID],
        check: QuickCheckResponse,
        guide_text: str,
    ) -> None:
        result = AnalysisResult(
            user_id=user_id,
            drug_ids_encrypted=self._enc.encrypt([str(d) for d in drug_ids]),
            findings_snapshot_encrypted=self._enc.encrypt(
                [finding.model_dump(mode="json") for finding in check.findings]
            ),
            risk_level=check.risk_level,
            model_name=settings.OLLAMA_MODEL,
            action_guide_encrypted=self._enc.encrypt(guide_text),
        )
        self.db.add(result)
        await self.db.commit()
