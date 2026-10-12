"""공공데이터 응답 파싱에 쓰는 순수 함수 모음 — DB/HTTP에 의존하지 않는다."""
import json
import re
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
