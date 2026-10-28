import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import get_encryptor
from app.core.logging import logger
from app.models.analysis_result import AnalysisResult
from app.schemas.analysis import AnalysisGuideResponse, QuickCheckResponse
from app.services.drug_service import DrugService
from app.services.glossary import find_entries
from app.services.ollama_client import OllamaClient, OllamaUnavailableError
from app.services.user_service import UserService

_MAX_FIELD_CHARS = 800  # 프롬프트 길이 방어 — 공공데이터 텍스트가 길 수 있어 필드당 상한


def _clip_field(text: str) -> str:
    """필드를 상한 안으로 자른다. 줄 경계가 가까이 있으면 거기서 잘라 문장 중간에서 끊기지 않게 한다
    (허가사항 전문은 항목 번호 줄 단위라, 중간에서 끊긴 항목을 모델이 그럴듯하게 이어 쓰곤 했다)."""
    if len(text) <= _MAX_FIELD_CHARS:
        return text
    head = text[:_MAX_FIELD_CHARS]
    cut = head.rfind("\n")
    return head[:cut] if cut >= _MAX_FIELD_CHARS // 2 else head
_MAX_ATTEMPTS = 2  # 검사에 걸린 답은 한 번만 다시 생성하고, 그래도 안 되면 폴백 문구

_FALLBACK_GUIDE_TEXT = (
    "지금 AI 설명을 생성할 수 없습니다. 위 판정 결과는 식약처 DUR 공공데이터와 "
    "등록하신 건강정보(알레르기·나이·임신 여부)에 근거해 이미 확정된 것이니 그대로 "
    "참고하시고, 자세한 대응은 의사·약사와 상담해 주세요."
)

# 내부 등급 코드(critical 등)를 프롬프트에 그대로 넣으면 모델이 "critical 등급"처럼
# 화면에 따라 쓴다 — 사용자에게 보이는 말로 바꿔서 넘긴다.
_RISK_LABEL = {"critical": "위험", "caution": "주의", "safe": "안전"}
_FINDING_LABEL = {
    "contraindicated": "병용금기(함께 먹으면 안 되는 조합)",
    "duplicate_ingredient": "동일 성분 중복(같은 성분을 겹쳐 먹게 됨)",
    "duplicate_effect_group": "효능군 중복(비슷한 작용의 약을 겹쳐 먹게 됨)",
}
_AGE_RULE_LABEL = {"age_taboo": "특정 연령대 금기", "elderly_caution": "노인 주의(만 65세 이상)"}

# 대응 문장은 AI에 맡기지 않고 판정 종류별로 코드가 붙인다 — 한 문장을 모든 경우에 쓰면
# 알레르기 성분이 든 약에도 "끊지 말라"가 붙기 때문이다.
# 서비스가 직접 하는 말이 되므로 진단·처방이 아니라 "알리고 확인·상담" 수준으로만 쓴다.
_CLOSING = {
    "allergy": "이 약을 먹기 전에(이미 먹고 있다면 지금 바로) 의사나 약사에게 알레르기가 있다고 알리고 복용해도 되는지 확인하세요.",
    "pregnancy": "임신 중이라는 사실을 의사나 약사에게 알리고 이 약을 계속 써도 되는지 상담하세요.",
    "age": "나이에 맞는 약인지 의사나 약사와 상담하세요.",
    # 처방·조제 때의 DUR 점검은 의사·약사가 이미 받으므로 처방자를 지목하지 않고 "알리고 확인"으로 말한다.
    # 끊으면 위험한 약이 있어 "임의로 끊지 말라"는 남긴다.
    "combination": "의사나 약사에게 이 두 약을 함께 쓰고 있다고 알리고 확인해 보세요. 이미 드시는 중이라면 임의로 끊거나 바꾸지는 마세요.",
    # 이 앱의 경고가 값을 하는 곳은 처방 점검에 잡히지 않는 약(일반의약품 등)을 사용자가 더할 때이므로, 일반의약품이 낀
    # 조합에는 그 상황에 맞는 문장을 쓴다.
    "combination_otc": (
        "처방 없이 산 약은 처방 점검에 잡히지 않을 수 있어요. 함께 드시기 전에 의사나 약사에게 이 두 약을 같이 써도 되는지 확인해 보세요. "
        "이미 드시는 중이라면 임의로 끊거나 바꾸지는 마세요."
    ),
}


def _no_findings_text(drug_count: int) -> str:
    return (
        f"함께 복용 중인 약 {drug_count}개 사이에서 식약처 DUR 공공데이터 기준으로 확인된 문제는 없습니다. "
        "다만 이 확인은 DUR에 등록된 병용금기·성분 중복 규칙만 대상으로 하므로, 모든 상호작용이 없다는 뜻은 아닙니다.\n\n"
        "걱정되는 점이 있으면 의사나 약사와 상담하세요."
    )


def closing_for(check: QuickCheckResponse, otc_involved: bool = False) -> str:
    """걸린 판정 종류에 맞는 대응 문장(위험한 것부터). 해당 없으면 일반 상담 안내.

    otc_involved: 병용·중복 판정에 일반의약품이 낀 경우 — 처방 점검에 안 잡히는 약을 더하는 상황에 맞는 문장을 쓴다."""
    kinds = [
        ("allergy", check.allergy_conflicts),
        ("pregnancy", check.pregnancy_cautions),
        ("age", check.age_cautions),
        ("combination_otc" if otc_involved else "combination", check.findings),
    ]
    lines = [_CLOSING[kind] for kind, items in kinds if items]
    return "\n".join(lines) or "걱정되는 점이 있으면 의사나 약사와 상담하세요."

# 설명은 DB 근거(DUR 원문·약 분류와 효능·출처 있는 용어 풀이) 안에서만 쓴다. 약 소개와 용어 풀이는 허용하고,
# 입력에 없는 작용 원리·연구 인용과 대체 약·복용 시간 조절 같은 제안은 금지한다. 말투는 앱 화면과 같은 해요체이며,
# 맥락 설명만으로는 말투가 따라오지 않아 끝의 말투 예시가 필요하다(예시는 내용이 아니라 말투·순서만 보여 준다).
_SYSTEM_PROMPT = """당신은 '굿메디슨' 약 관리 앱의 설명 도우미입니다.
이 앱을 쓰는 사람은 의학 지식이 없는 일반 시민(어르신과 보호자 포함)입니다. 사용자는 내 약 목록 화면에서
'위험' 또는 '주의' 표시를 보고, 그게 무슨 뜻인지 알고 싶어서 이 설명을 읽습니다.
사용자가 알고 싶은 것은 ① 내 약에 어떤 문제가 있는지 ② 왜 그런지 ③ 어떻게 하면 되는지입니다.
말투는 앱 화면과 같은 '~해요', '~예요' 체로, 약국에서 차분히 설명해 주는 약사처럼 짧고 쉽게 쓰세요.
어려운 의학 용어는 쓰지 말고, 꼭 써야 하면 풀이를 붙이세요.

원칙:
1. 오직 [판정 결과]·[약품 정보]·[용어 풀이] 안의 내용만 근거로 설명하세요.
   그 안에 없는 증상, 장기, 작용 원리, 확률, 연구 결과를 덧붙이거나 지어내지 마세요.
   특히 "위벽을 자극해서"처럼 입력에 없는 이유를 일반 상식으로 만들어 붙이지 마세요.
2. 왜 위험한지는 "식약처가 정한 기준으로는 …"처럼 [판정 결과]의 이유를 쉬운 말로 옮겨 말하세요.
3. 이 판정은 이미 식약처 공공데이터(DUR)와 사용자 건강정보로 확정된 결과입니다.
   판정을 바꾸거나 재평가하지 말고, 그대로 받아들여 쉽게 풀어 설명만 하세요.
4. 알레르기·나이·임신 항목은 약 한 가지에 대한 경고입니다. 두 약 사이의 상호작용처럼
   설명하지 마세요.
5. 복용을 스스로 끊거나 바꾸라고 권하지 마세요. 대체 약, 다른 치료법, 복용 시간 조절도 제안하지 마세요.
   대응은 "의사나 약사와 상담하세요" 정도로만 쓰세요.
6. 첫 문단에서는 [약품 정보]의 분류·효능을 근거로 각 약이 무엇에 쓰는 약인지 한 문장씩 소개하세요.
   효능이 길면 첫 항목만 짧게 요약하고, 정보가 없는 약은 소개를 생략하세요.
7. 둘째 문단은 두 문장 이내로 쓰세요. 첫 문장은 식약처가 정한 기준(= [판정 결과]에 적힌 위험)을 말하고,
   [용어 풀이]에 있는 용어가 나오면 둘째 문장에서 그 풀이만 전하세요. 풀이는 문장을 거의 그대로 옮기고
   바꿔 말하며 뜻을 바꾸지 마세요. 풀이에 없는 용어는 풀이하지 말고 원문 표현 그대로 쓰세요.
   왜 그런 위험이 생기는지 원리는 설명하지 마세요.
8. 전체는 문장 3~6개, 문단은 2개로 쓰세요. 사용자를 "당신"이라고 부르지 마세요.
   마크다운(**, #, 글머리 기호, 번호 목록), 영어 단어, 한자는 쓰지 마세요.

[말투와 구성 예시 — 내용이 아니라 말투와 순서만 참고하세요]
가나정은 혈압을 낮추는 약이에요. 다라정은 열을 내리는 약이에요.

식약처가 정한 기준으로는 이 두 약을 함께 먹으면 ○○ 문제가 생길 위험이 있어서, 같이 쓰지 않도록 되어 있어요."""

_MARKDOWN_EMPHASIS = re.compile(r"\*\*|__")
_MARKDOWN_LINE_PREFIX = re.compile(r"^[ \t]*(?:#{1,6}|[-*•]|\d+[.)])[ \t]+", re.M)
_HAN_OR_KANA = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# \b는 한글도 단어 문자로 봐서 "critical인"을 못 잡는다 — 영문자 경계만 본다
_RISK_CODE = re.compile(r"(?<![A-Za-z])(?:critical|caution|safe)(?![A-Za-z])", re.I)
_STOP_WORD = re.compile(r"중단|끊")
_NEGATION_AFTER_STOP = re.compile(r"^[^.!?\n]{0,12}?(?:지\s*마|지\s*말|면\s*안)")
# 금기 조합에 대체 약·다른 치료법·시간차 복용을 권하면 위험하므로 그런 제안 문장은 걸러 낸다.
_ALTERNATIVE = re.compile(
    r"대체\s*(?:약|의약품|치료|요법)|대안|교체"
    r"|다른\s*(?:(?:치료\s*)?(?:방법|법)|옵션|(?:시간|시점)(?:에|대에))"
    r"|다른\s*약(?:물)?(?:으로|을\s*(?:고려|처방|사용|복용하))"
    r"|복용\s*시간(?:을|이)?\s*(?:조절|달리|나누)"
    r"|치료\s*(?:방법|법|계획)(?:을|에\s*대해)?\s*(?:찾|고려|논의|세우)"
)
# 입력에 없는 권위 인용("연구 결과가 있습니다")은 근거 없는 주장이므로 걸러 낸다
_CITATION = re.compile(r"연구\s*(?:결과|에\s*따르면|에서)|임상\s*(?:시험|연구)|논문")
# "…는 …한다는 뜻이에요"류 정의 문장 — 용어집에 있는 용어가 아니면 모델이 제 지식으로 푼 것이다
_DEFINITION = re.compile(r"(?:란|이란|은|는)\s[^.!?]*(?:뜻|의미|말)(?:이에요|이예요|예요|해요|입니다|합니다)")


def sanitize_guide_text(text: str) -> str:
    """앱은 받은 문자열을 그대로 그리므로 마크다운 기호를 걷어낸다(내용은 유지)."""
    text = _MARKDOWN_EMPHASIS.sub("", text)
    text = _MARKDOWN_LINE_PREFIX.sub("", text)
    # 모델이 "알레르기 반응"을 "알레르 반응"으로 쓰는 일이 잦아 교정한다
    text = re.sub(r"알레르(?!기)", "알레르기", text)
    # 지시해도 "당신이…"가 남는다 — 주어를 빼도 자연스러운 한국어라 지운다
    text = re.sub(r"당신(?:께서|에게|이|은|의)?\s*", "", text)
    # 해요체 표기 교정: "약이예요" → "약이에요"
    text = text.replace("이예요", "이에요")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_TRAILING_ADVICE = re.compile(r"(?:^|(?<=[.!?])\s+)[^.!?]*상담[^.!?]*[.!?]?\s*$")


def drop_trailing_advice(text: str) -> str:
    """AI가 끝에 쓴 상담 권유 문장을 떼어 낸다 — 대응 문장은 종류별로 코드가 붙인다.

    AI에게 아예 대응을 쓰지 말라고 하면 답이 짧아져 한국어를 벗어나는 일이 잦아진다.
    그래서 쓰게 두고 뒤에서 뗀다."""
    body = text.strip()
    while True:
        trimmed = _TRAILING_ADVICE.sub("", body).rstrip()
        if trimmed == body or not trimmed:
            return body
        body = trimmed


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


def repair_guide_text(text: str) -> tuple[str, list[str]]:
    """내보내면 안 되는 문장만 덜어 낸다 — (남은 글, 덜어 낸 이유들).

    대응 문장은 코드가 따로 붙이므로 AI 답에서 문제 문장을 빼도 안내가 비지 않는다.
    답 전체를 버리고 재생성하면 알레르기·임부금기에서 모델이 자연스럽게 쓰는
    "복용을 중단하세요" 한 문장 때문에 폴백으로 끝나는 일이 많아, 문제 문장만 뺀다.
    한자·가나가 나오면 그 문장부터 끝까지 버린다(그 뒤는 대개 언어가 바뀐 채 이어진다).
    """
    removed: list[str] = []
    paragraphs: list[str] = []
    cut = False
    for para in text.split("\n\n"):
        kept = []
        for sentence in _SENTENCE_END.split(para.strip()):
            if not sentence:
                continue
            problem = guide_text_problem(sentence)
            if problem == "한자·가나 섞임":
                removed.append(problem)
                cut = True
                break
            if problem:
                removed.append(problem)
                continue
            kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
        if cut:
            break
    return drop_trailing_advice("\n\n".join(paragraphs)), removed


def guide_text_problem(text: str) -> str | None:
    """사용자에게 내보내면 안 되는 답이면 그 이유를, 괜찮으면 None을 돌려준다.

    지시문만으로는 막히지 않는 것들을 결정론적으로 거른다.
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
    if _ALTERNATIVE.search(text):
        return "대체 약·치료법 제안"
    if _CITATION.search(text):
        return "근거 없는 연구 인용"
    if _DEFINITION.search(text) and not find_entries(text):
        return "출처 없는 용어 풀이"
    return None


def _finding_lines(check: QuickCheckResponse) -> list[str]:
    lines = []
    for finding in check.findings:
        kind = _FINDING_LABEL.get(finding.interaction_type, "주의가 필요한 조합")
        tags = f" [주요 위험: {', '.join(finding.risk_tags)}]" if finding.risk_tags else ""
        lines.append(f"- {finding.drug1_name} + {finding.drug2_name}: {kind} — {finding.mechanism or '정보 없음'}{tags}")
    return lines


def _allergy_lines(check: QuickCheckResponse) -> list[str]:
    return [
        f"- {c.drug_name}: 등록한 알레르기 '{c.matched_allergy_term}'와 이 약의 성분 '{c.matched_ingredient}'이 겹침"
        for c in check.allergy_conflicts
    ]


def _age_lines(check: QuickCheckResponse) -> list[str]:
    return [
        f"- {c.drug_name}: {_AGE_RULE_LABEL.get(c.rule_type, '연령 관련 주의')} — {c.prohibit_content or '정보 없음'}"
        for c in check.age_cautions
    ]


def _pregnancy_lines(check: QuickCheckResponse) -> list[str]:
    return [
        f"- {c.drug_name}: 임부금기(임신 중 사용을 피해야 함) — {c.prohibit_content or '정보 없음'}"
        + (f" (적용 범위: {c.remark})" if c.remark else "")
        for c in check.pregnancy_cautions
    ]


def _involved_drug_ids(check: QuickCheckResponse) -> list[uuid.UUID]:
    """판정 결과에 나온 모든 약의 id (쌍 판정은 양쪽, 사용자 정보 판정은 해당 약)."""
    ids: set[uuid.UUID] = set()
    for finding in check.findings:
        ids |= {finding.drug1_id, finding.drug2_id}
    for group in (check.allergy_conflicts, check.age_cautions, check.pregnancy_cautions):
        ids |= {c.drug_id for c in group}
    return list(ids)


def _drug_line(drug) -> str:
    """약 한 개의 프롬프트용 한 줄. e약은요 데이터가 없는 약(대부분)은 이름만 남아 한국어 맥락이 짧아지는데,
    그때 모델이 중국어로 넘어갈 수 있다. 분류명을 넣고 마지막 줄에 "한국어로만" 지시를 두어 막는다."""
    parts = [f"[{drug.simple_name or drug.item_name}]"]
    for label, value in (
        ("분류", drug.class_name),
        ("효능", drug.efcy_qesitm),
        ("주의사항", drug.atpn_qesitm),
        ("상호작용", drug.intrc_qesitm),
        ("부작용", drug.se_qesitm),
    ):
        if value:
            # 분류명은 짧아 자르지 않고, 허가사항 원문처럼 긴 필드만 줄 경계로 자른다
            parts.append(f"{label}: {value if label == '분류' else _clip_field(value)}")
    return " / ".join(parts)


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
        if not (check.findings or check.allergy_conflicts or check.age_cautions or check.pregnancy_cautions):
            # 설명할 문제가 없으면 모델을 부르지 않는다. 프롬프트에 약 정보가 없으면 모델이 약 개수를 틀리게
            # 말하고 "안전하다"고까지 단정하는데, DUR에 없는 상호작용은 못 찾으므로 "안전"을 말하면 안 된다.
            # 정해진 문장 + 약 개수만 사실대로 쓴다.
            guide_text = _no_findings_text(len(drug_ids))
            await self._persist(user_id, drug_ids, check, guide_text)
            return AnalysisGuideResponse(
                risk_level=check.risk_level, guide_text=guide_text, is_ai_generated=False
            )

        prompt = await self._build_prompt(user_id, check)
        otc_involved = await self._otc_involved(check)

        guide_text, is_ai_generated = _FALLBACK_GUIDE_TEXT, False
        try:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                raw = sanitize_guide_text(await self._ollama.generate(prompt, system=_SYSTEM_PROMPT))
                candidate, removed = repair_guide_text(raw)
                if removed:
                    logger.info(f"AI 가이드 문장 제거({', '.join(sorted(set(removed)))}) — 시도 {attempt}")
                if candidate:
                    guide_text = f"{candidate}\n\n{closing_for(check, otc_involved)}"
                    is_ai_generated = True
                    break
                logger.warning(f"AI 가이드 응답에 남길 문장이 없음 — 시도 {attempt}/{_MAX_ATTEMPTS}")
            else:
                logger.warning("AI 가이드 재생성도 검사 실패 — 폴백 문구로 대체 (판정 결과는 영향 없음)")
        except OllamaUnavailableError:
            logger.warning("Ollama 가이드 생성 실패 — 폴백 문구로 대체 (판정 결과는 영향 없음)")

        await self._persist(user_id, drug_ids, check, guide_text)

        return AnalysisGuideResponse(
            risk_level=check.risk_level, guide_text=guide_text, is_ai_generated=is_ai_generated
        )

    async def _otc_involved(self, check: QuickCheckResponse) -> bool:
        """병용·중복 판정에 일반의약품이 하나라도 끼었는가."""
        ids = {f.drug1_id for f in check.findings} | {f.drug2_id for f in check.findings}
        if not ids:
            return False
        drugs = await DrugService(self.db).get_drugs_by_ids(list(ids))
        return any((d.etc_otc_name or "").strip() == "일반의약품" for d in drugs.values())

    async def _health_lines(self, user_id: uuid.UUID) -> list[str]:
        """사용자 건강정보/알레르기. 복호화 실패는 UserService가 필드별로 격리 처리하므로 있으면 쓰고
        없으면 생략한다 (가이드 생성 전체를 막지 않음)."""
        lines: list[str] = []
        try:
            user = await UserService(self.db).get_user(user_id)
            conditions = getattr(user, "health_conditions", None)
            allergies = getattr(user, "allergy_info", None)
            if conditions:
                lines.append(f"건강 상태: {', '.join(conditions)}")
            if allergies:
                lines.append(f"알레르기: {', '.join(allergies)}")
        except Exception:
            logger.warning("사용자 건강정보 조회 실패 — 컨텍스트 없이 가이드 생성 진행", exc_info=True)
        return lines

    async def _build_prompt(self, user_id: uuid.UUID, check: QuickCheckResponse) -> str:
        finding_lines = _finding_lines(check)
        age_lines = _age_lines(check)
        pregnancy_lines = _pregnancy_lines(check)
        drugs = await DrugService(self.db).get_drugs_by_ids(_involved_drug_ids(check))
        drug_lines = [_drug_line(drug) for drug in drugs.values()]
        health_lines = await self._health_lines(user_id)

        sections = [f"[판정 결과] 전체 위험도: {_RISK_LABEL.get(check.risk_level, check.risk_level)}"]
        for title, lines in (
            ("함께 먹을 때의 문제", finding_lines),
            ("알레르기 성분 충돌", _allergy_lines(check)),
            ("나이 관련 DUR 규칙", age_lines),
            ("임신 중 금기", pregnancy_lines),
        ):
            if lines:
                sections.append(f"[{title}]\n" + "\n".join(lines))
        if len(sections) == 1:
            sections.append("(확인된 문제 없음)")
        sections.append("[약품 정보]\n" + ("\n".join(drug_lines) or "(약품 상세 정보 없음)"))
        # 판정 문장에 나온 용어 중 출처 있는 풀이가 있는 것만 근거로 넘긴다(없는 용어는 풀이하지 않는다)
        glossary = find_entries("\n".join(finding_lines + age_lines + pregnancy_lines))
        if glossary:
            sections.append("[용어 풀이]\n" + "\n".join(f"- {e.term}: {e.definition}" for e in glossary))
        if health_lines:
            sections.append("[사용자 정보]\n" + "\n".join(health_lines))
        # 지시에서 "대응"을 빼지 않는다 — 대응 문장은 뒤에서 코드가 붙이지만 지시에서 빼면 답이 짧아져 한국어를 벗어난다
        # (drop_trailing_advice 주석 참고)
        sections.append(
            "위 정보만 근거로, 각 약이 무엇에 쓰는 약인지와 왜 위험한지, 어떻게 대응해야 하는지 한국어로만 설명해 주세요."
        )

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
