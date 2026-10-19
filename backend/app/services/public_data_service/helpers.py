"""공공데이터 응답 파싱에 쓰는 순수 함수 모음 — DB/HTTP에 의존하지 않는다."""
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from typing import Any

_AGE_CRITERIA_RE = re.compile(r'(\d+)\s*(세|개월)\s*(미만|이상|이하|초과)')


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _clean_text(value: Any) -> str | None:
    """_clean + 원본이 통째로 따옴표로 감싸 내려주는 경우(임부금기 REMARK/PROHBT_CONTENT에서
    일부 행이 '"2등급(…)"' 형태) 바깥 따옴표만 벗긴다. 본문 중간의 따옴표는 건드리지 않는다."""
    s = _clean(value)
    if s and len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s or None


def _make_drug_key(name: str) -> str:
    s = str(name)
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'밀리그램', 'mg', s)
    s = re.sub(r'밀리그람', 'mg', s)
    s = re.sub(r'마이크로그램', 'mcg', s)
    s = re.sub(r'마이크로그람', 'mcg', s)
    s = re.sub(r'그램', 'g', s)
    s = re.sub(r'그람', 'g', s)
    s = s.replace(' ', '')
    s = re.sub(r'[^\w]', '', s, flags=re.UNICODE)
    return s.lower()


def _make_simple_name(item_name: str) -> str:
    name = re.sub(r'[\(\[（][^\)\]）]*[\)\]）]', '', item_name).strip()
    return name if name else item_name


def _parse_ingredients(ingr_str: str) -> list[dict]:
    amount_pattern = re.compile(r'(\d+\.?\d*)\s*(mg|mcg|g|IU|%|μg)', re.IGNORECASE)

    separators = [",", "/", "+", ";", "·"]
    parts = [ingr_str]
    for sep in separators:
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts

    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        amount = ""
        m = amount_pattern.search(part)
        if m:
            amount = m.group(0).strip()
            kor_name = amount_pattern.sub('', part).strip()
        else:
            kor_name = part

        result.append({
            "kor": kor_name,
            "eng": "",
            "amount": amount,
            "dur_code": "",
        })

    return result


def _parse_main_ingr(main_ingr: str) -> list[dict]:
    result = []
    for part in main_ingr.split('/'):
        part = part.strip()
        m = re.match(r'\[([^\]]+)\](.+)', part)
        if m:
            result.append({"kor": m.group(2).strip(), "eng": "", "amount": "", "dur_code": m.group(1)})
    return result


def _parse_age_criteria(text: str | None) -> tuple[int | None, str | None, str | None]:
    """PROHBT_CONTENT 원문에서 "OO세 미만" 같은 숫자 나이 기준을 뽑는다.

    실측(2026-09-12, 500건 샘플)상 이 패턴이 있는 행은 3.6%뿐이다 — 나머지는
    "소아"/"영아" 같은 범주어이거나 나이 언급이 아예 없어서 숫자로 못 뽑는다.
    실패하면 (None, None, None) — 호출부가 원문은 저장하되 판정에는 안 쓴다.
    """
    if not text:
        return None, None, None
    m = _AGE_CRITERIA_RE.search(text)
    if not m:
        return None, None, None
    return int(m.group(1)), m.group(2), m.group(3)


def _parse_tag_array(raw: str) -> list[str]:
    """LLM 응답에서 첫 `[` ~ 마지막 `]` 사이를 JSON 배열로 파싱. 실패 시 []."""
    s, e = raw.find("["), raw.rfind("]")
    if s == -1 or e == -1 or e < s:
        return []
    try:
        arr = json.loads(raw[s:e + 1])
    except (ValueError, TypeError):
        return []
    out, seen = [], set()
    for x in arr:
        x = str(x).strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:4]


def make_ingredient_resolver(pairs: Iterable[tuple[str | None, str | None]]) -> Callable[[str], str | None]:
    """`(성분명, DUR 성분코드)` 쌍에서 "성분명 → 코드" 해소 함수를 만든다.

    정규화한 이름이 완전히 같으면 그 코드, 아니면 접두(염 형태 차이: '트리메부틴' ↔
    '트리메부틴말레산염')가 맞는 코드. substring 매칭은 '우레아→히드록시우레아' 같은
    오매칭이 나서 쓰지 않는다(CLAUDE.md "상용약품 DUR 매칭 개선 시도" 2번)."""
    name_to_code: dict[str, str] = {}
    for ingr_kor, ingr_code in pairs:
        if not ingr_kor or not ingr_code:
            continue
        key = _make_drug_key(ingr_kor)
        if key and key not in name_to_code:
            name_to_code[key] = ingr_code
    code_keys = sorted(name_to_code)

    def _resolve(cand: str) -> str | None:
        key = _make_drug_key(cand)
        if len(key) < 3:
            return None
        code = name_to_code.get(key)
        if code:
            return code
        for ck in code_keys:
            if ck.startswith(key) or key.startswith(ck):
                return name_to_code[ck]
        return None

    return _resolve


def permit_doc_to_text(doc_xml: str | None, max_chars: int | None = None) -> str | None:
    """허가정보 상세의 `EE/UD/NB_DOC_DATA`(CDATA가 든 XML) → 읽을 수 있는 평문.

    SECTION/ARTICLE 제목은 한 줄, PARAGRAPH는 그 아래 줄로 낸다. `max_chars`를 주면 제목 단위
    블록(예: "1. 다음 환자에는 투여하지 말 것")을 앞에서부터 담다가 넘으면 거기서 멈추고
    말줄임을 붙인다 — 문장 중간에서 자르지 않고, 금기가 앞에 오는 문서 구조상 가장 중요한
    내용이 남는다. 첫 블록은 항상 담는다. XML이 깨져 있으면 태그만 걷어낸 텍스트로 폴백."""
    if not doc_xml or not doc_xml.strip():
        return None
    blocks: list[list[str]] = []
    try:
        root = ET.fromstring(doc_xml.strip())
        for el in root.iter():
            if el.tag in ("SECTION", "ARTICLE"):
                title = (el.get("title") or "").strip()
                if title:
                    blocks.append([title])
            elif el.tag == "PARAGRAPH":
                line = " ".join((el.text or "").split())
                if line:
                    if not blocks:
                        blocks.append([])
                    blocks[-1].append(line)
    except ET.ParseError:
        plain = " ".join(re.sub(r"<[^>]+>", " ", doc_xml).split())
        blocks = [[plain]] if plain else []

    texts = ["\n".join(b) for b in blocks if b]
    if not texts:
        return None
    if max_chars is None:
        return "\n".join(texts)
    out: list[str] = []
    used = 0
    for block in texts:
        if out and used + len(block) > max_chars:
            out.append("…(이하 생략 — 전문은 식약처 허가사항 참고)")
            break
        out.append(block)
        used += len(block)
    return "\n".join(out)
