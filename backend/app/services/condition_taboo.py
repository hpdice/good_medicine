"""건강 상태 금기 — 허가사항의 "다음 환자에는 투여하지 말 것" 항목에 사용자가 등록한 건강 상태가 있으면 금기로 본다.

출처는 허가사항 본문(`drugs.atpn_qesitm`)이고, 항목 문장을 **그대로** 보여 준다. 의학적 판단이나 동의어 확장은 하지 않는다 —
항목에 사용자가 쓴 말이 글자 그대로 들어 있을 때만 잡는다('위궤양'과 '소화성 궤양'처럼 표현이 다르면 못 찾는다, 미탐지).
"신중히 투여할 것" 같은 다른 항목은 금기가 아니므로 보지 않는다."""
import re

# "다음 환자에는 투여하지 말 것", "다음과 같은 사람은 이 약을 복용하지 마십시오" 등 금기 목록의 제목. 줄 **맨 앞**이 "다음"(앞에
# "1."·"1)" 번호는 허용)인 짧은 줄만 제목으로 본다 — 다른 항목 문장 속의 "…다음 … 투여하지 않는다"를 제목으로 오인하면
# 그 뒤 항목 전부가 금기 목록으로 섞여 들어온다.
_CONTRA_HEADING = re.compile(
    r"^\s*(?:\d+[.)]\s*)?다음[^\n]{0,30}?(?:환자|사람|경우|대상)[^\n]{0,20}?(?:투여|복용|사용)(?:하지|을 피하)[^\n]{0,15}?(?:말|마)"
)
_TOP_HEADING = re.compile(r"^\s*\d+\.\s*\S")  # "2. 다음 환자에는 신중히 투여할 것." 같은 새 큰 제목
_ITEM_START = re.compile(r"^\s*(?:\d+\)|[•·ㆍ▪])\s*")
_MAX_HEADING_LEN = 80
_MAX_SENTENCE_LEN = 300
MIN_CONDITION_LEN = 2  # '간' 같은 한 글자는 너무 많은 낱말에 들어 있어 비교하지 않는다


# 병명 앞에 붙어도 같은 병을 가리키는 정도 표시(중증간장애 = 중증 간장애). 그 밖의 한글이 바로 앞에 붙으면 다른 낱말이다
# (폐고혈압·문맥고혈압은 고혈압이 아니다).
_SEVERITY_PREFIXES = ("중증", "경증", "중등도", "심한", "급성", "만성", "활동성", "진행성")


def _term_pattern(term: str) -> re.Pattern[str]:
    """띄어쓰기 차이는 무시하고(소화성궤양 = 소화성 궤양), 낱말 중간에 든 것은 건너뛴다(폐고혈압 ≠ 고혈압)."""
    body = r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", term))
    boundary = r"(?:(?<![가-힣A-Za-z0-9])" + "".join(f"|(?<={re.escape(p)})" for p in _SEVERITY_PREFIXES) + ")"
    return re.compile(boundary + body, re.IGNORECASE)


def contraindication_items(text: str | None) -> list[str]:
    """허가사항 본문에서 "투여하지 말 것" 목록의 항목 문장들. 제목이 없으면 빈 목록."""
    if not text:
        return []
    items: list[str] = []
    capturing = False
    bullets: list[str] = []
    plain: list[str] = []

    def flush() -> None:
        nonlocal bullets, plain
        if bullets:
            items.extend(bullets)
        else:
            items.extend(plain)
        bullets, plain = [], []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if capturing and _TOP_HEADING.match(line) and not _ITEM_START.match(line):
            flush()
            capturing = False
        if not capturing:
            if len(stripped) <= _MAX_HEADING_LEN and _CONTRA_HEADING.match(stripped):
                capturing = True
            continue
        if _ITEM_START.match(line):
            bullets.append(_ITEM_START.sub("", line, count=1).strip())
        elif bullets:
            bullets[-1] += " " + stripped  # 줄바꿈으로 이어진 항목
        else:
            plain.append(stripped)
    if capturing:
        flush()
    return [i[:_MAX_SENTENCE_LEN] for i in items if i]


_PAREN = re.compile(r"[(（][^()（）]*[)）]")


def _without_parentheses(item: str) -> str:
    """괄호 안은 이유·설명이라 비교에서 뺀다 — "크롬친화세포종 환자(…고혈압을 유발할 수 있다)"는 고혈압 환자의 금기가 아니다."""
    prev = None
    while prev != item:  # 중첩 괄호도 바깥까지
        prev, item = item, _PAREN.sub(" ", item)
    return item


def find_condition_taboo(text: str | None, conditions: list[str]) -> list[tuple[str, str]]:
    """사용자의 건강 상태 중 "투여하지 말 것" 항목에 글자 그대로 들어 있는 것 → [(건강 상태, 항목 문장)]. 상태마다 첫 항목만."""
    terms = [(c.strip(), _term_pattern(c)) for c in conditions if c and len(re.sub(r"\s+", "", c)) >= MIN_CONDITION_LEN]
    if not terms:
        return []
    items = contraindication_items(text)
    found: list[tuple[str, str]] = []
    for original, pattern in terms:
        for item in items:
            if pattern.search(_without_parentheses(item)):
                found.append((original, item))
                break
    return found
