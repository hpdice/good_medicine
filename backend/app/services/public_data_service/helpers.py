"""공공데이터 응답 파싱에 쓰는 순수 함수 모음 — DB/HTTP에 의존하지 않는다."""
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any


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
    """`[Mxxxx]성분명` 목록 → [{kor, eng, amount, dur_code}]. 구분자는 `/`(허가 목록)와 `|`(허가정보 상세)다 —
    `|`를 못 쪼개면 복합제의 성분 전부가 첫 성분 이름 하나로 묶여 나머지 성분의 판정을 놓친다."""
    result = []
    for part in re.split(r'[/|]', main_ingr):
        part = part.strip()
        m = re.match(r'\[([^\]]+)\](.+)', part)
        if m:
            result.append({"kor": m.group(2).strip(), "eng": "", "amount": "", "dur_code": m.group(1)})
    return result


def split_joined_ingr_names(ingr_name: list[dict] | None) -> list[dict]:
    """`ingr_name`에 `이름|[M…]이름`으로 한 항목에 묶여 저장된 이름을 항목 하나씩으로 쪼갠다(같은 이름은 하나만).
    원문(`main_item_ingr`)이 없는 약을 바로잡을 때 쓴다."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in ingr_name or []:
        parts = (item.get("kor") or "").split("|")
        for i, part in enumerate(parts):
            m = re.match(r'\[([^\]]+)\](.+)', part.strip())
            kor = (m.group(2) if m else part).strip()
            if not kor or kor in seen:
                continue
            seen.add(kor)
            out.append({**item, "kor": kor, "dur_code": m.group(1) if m else (item.get("dur_code") if i == 0 else "")})
    return out


def norm_ingr_eng(name: str | None) -> str | None:
    """영문 성분명 비교 키 — 유니코드 호환 정규화, 소문자, 공백 하나로. 염·`(as …)`은 그대로 둔다
    (완전 일치가 1차, 염 정리는 매칭 단계에서 2차로만 쓴다)."""
    if not name:
        return None
    s = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', name)).strip().lower()
    return s or None


_AGE_BASE_RE = re.compile(r'^\s*(\d+)\s*(세|개월|주)\s*(미만|이상|이하|초과)\s*$')


def parse_age_base(text: str | None) -> tuple[int | None, str | None, str | None]:
    """DUR 성분정보 `AGE_BASE`("18세 미만", "4주 미만")를 (기준, 단위, 방향)으로. 형식이 다르면 셋 다 None.
    값 전체가 이 형식일 때만 읽는다(문장 속 '4주 이상 투여' 같은 말을 나이로 오인하지 않게)."""
    m = _AGE_BASE_RE.match(text or "")
    if not m:
        return None, None, None
    return int(m.group(1)), m.group(2), m.group(3)


def ingredient_master_from_rows(
    rows_by_label: dict[str, list[dict]],
) -> dict[tuple[str, str | None, str | None], str | None]:
    """DUR 성분정보 응답(오퍼레이션 라벨별 행) → {(성분코드, 한글, 영문): 단일/복합}.
    같은 코드의 이름이 둘이면 덮어쓰지 않고 따로 둔다."""
    names: dict[tuple[str, str | None, str | None], str | None] = {}
    for items in rows_by_label.values():
        for item in items:
            # 병용금기는 한 행에 A(INGR_*)·B(MIXTURE_INGR_*) 두 성분이 있다. 나머지는 A만.
            for prefix in ("", "MIXTURE_"):
                code = _clean(item.get(f"{prefix}INGR_CODE"))
                if code:
                    kor = _clean(item.get(f"{prefix}INGR_KOR_NAME") or item.get(f"{prefix}INGR_NAME"))
                    names.setdefault((code, kor, _clean(item.get(f"{prefix}INGR_ENG_NAME"))),
                                     _clean(item.get(f"{prefix}MIX_TYPE")))
    return names


def _active_rows(items: Iterable[dict]) -> list[dict]:
    """DUR 성분정보 응답 중 삭제되지 않은 행(`DEL_YN`='정상')."""
    return [i for i in items if _clean(i.get("DEL_YN")) == "정상"]


def _join_unique(values: Iterable[str | None], sep: str) -> str | None:
    return sep.join(dict.fromkeys(v for v in values if v)) or None


def contraindication_rules_from_ingredient(items: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """DUR 성분정보 병용금기 행 → {(성분코드 a, b) (a<b): 규칙 값}.
    같은 쌍이 고시 개정·복합제별로 여러 행이면 가장 최근 고시일의 행들만 쓰고, 그 문구·비고를 중복 없이 합친다."""
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for item in _active_rows(items):
        a, b = _clean(item.get("INGR_CODE")), _clean(item.get("MIXTURE_INGR_CODE"))
        if a and b and a != b:
            by_pair.setdefault((min(a, b), max(a, b)), []).append(item)

    rules = {}
    for (a, b), rows in by_pair.items():
        latest = max(_clean(r.get("NOTIFICATION_DATE")) or "" for r in rows)
        rows = [r for r in rows if (_clean(r.get("NOTIFICATION_DATE")) or "") == latest]
        kor = {}
        for r in rows:
            kor.setdefault(_clean(r.get("INGR_CODE")), _clean(r.get("INGR_KOR_NAME")))
            kor.setdefault(_clean(r.get("MIXTURE_INGR_CODE")), _clean(r.get("MIXTURE_INGR_KOR_NAME")))
        rules[(a, b)] = {
            "ingr_kor_a": kor.get(a), "ingr_kor_b": kor.get(b),
            "prohibit_content": _join_unique((_clean_text(r.get("PROHBT_CONTENT")) for r in rows), "\n"),
            "remark": _join_unique((_clean_text(r.get("REMARK")) for r in rows), " / "),
        }
    return rules


def effect_groups_from_ingredient(items: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """DUR 성분정보 효능군중복 행 → {(성분코드, DUR_SEQ): {effect_name, sers_name}}."""
    groups = {}
    for item in _active_rows(items):
        code, seq = _clean(item.get("INGR_CODE")), _clean(item.get("DUR_SEQ"))
        effect = _clean(item.get("EFFECT_CODE") or item.get("EFFECT_NAME"))
        if code and seq and effect:
            groups[(code, seq)] = {"effect_name": effect, "sers_name": _clean(item.get("SERS_NAME"))}
    return groups


def age_rules_from_ingredient(items: Iterable[dict], *, with_age_base: bool) -> dict[str, dict]:
    """DUR 성분정보 특정연령대금기·노인주의 행 → {성분코드: 규칙 값}. 한 성분에 제형별 행이 여럿이면
    문구를 합치고, `with_age_base`면 그 행들의 `AGE_BASE`가 하나로 같을 때만 나이 기준을 채운다."""
    by_code: dict[str, list[dict]] = {}
    for item in _active_rows(items):
        code = _clean(item.get("INGR_CODE"))
        if code:
            by_code.setdefault(code, []).append(item)

    rules = {}
    for code, rows in by_code.items():
        threshold = unit = direction = None
        if with_age_base:
            bases = {_clean(r.get("AGE_BASE")) for r in rows}
            if len(bases) == 1:
                threshold, unit, direction = parse_age_base(bases.pop())
        rules[code] = {
            "ingr_kor": _clean(rows[0].get("INGR_NAME") or rows[0].get("INGR_KOR_NAME")),
            "prohibit_content": _join_unique((_clean_text(r.get("PROHBT_CONTENT")) for r in rows), "\n"),
            "age_threshold": threshold, "age_unit": unit, "age_direction": direction,
        }
    return rules


_MAX_QTY_UNIT_MG = {"그램": 1000.0, "밀리그램": 1.0, "마이크로그램": 0.001}
# '4,000밀리그램', '아세트아미노펜 4,000밀리그램', '트리플루리딘으로 160밀리그램'. 괄호('(고령자)', '(미분화)')·
# '주1회'·'또는'이 섞인 값은 조건이 붙은 기준이라 일부러 맞지 않게 둔다.
_MAX_QTY_PART_RE = re.compile(
    r'^\s*(?:([가-힣A-Za-z][^\d/()]*?)\s*(?:으로서|로서|으로|로)?\s+)?([\d,]+(?:\.\d+)?)\s*(그램|밀리그램|마이크로그램)\s*$'
)
_MIX_INGR_RE = re.compile(r'\[(D\d+)\][^(/]*\(([^)]*)\)')


def parse_max_qty(text: str | None) -> list[tuple[str | None, float]] | None:
    """DUR 용량주의 `MAX_QTY`(1일 최대 투여량) → [(성분명 또는 None, mg)]. 복합제는 '/'로 성분마다 나뉜다.
    한 조각이라도 못 읽으면 None(조건부 기준·다른 단위는 판정하지 않는다)."""
    if not text or not text.strip():
        return None
    parts = []
    for piece in text.split("/"):
        m = _MAX_QTY_PART_RE.match(piece)
        if not m:
            return None
        name, number, unit = m.groups()
        mg = round(float(number.replace(",", "")) * _MAX_QTY_UNIT_MG[unit], 6)
        parts.append((name.strip() if name else None, mg))
    return parts


def _dose_limits(code: str, kor: str | None, mix: dict[str, str], parts: list[tuple[str | None, float]]) -> dict[str, float]:
    """`parse_max_qty` 결과를 성분코드별 상한으로. 단일제 규칙은 이름과 무관하게 그 성분의 상한이다. 복합제는
    이름 없는 값은 규칙의 주성분(INGR_CODE), 이름 있는 값은 그 이름이 성분명으로 시작하는 코드 하나에만 붙인다
    ('로사르탄칼륨 100밀리그램' → 로사르탄). 맞는 코드가 없거나 둘 이상이면 그 값은 버린다."""
    if not mix:
        return {code: parts[0][1]} if len(parts) == 1 else {}
    names = {code: kor or "", **mix}
    limits: dict[str, float] = {}
    for name, mg in parts:
        if name is None:
            hits = [code]
        else:
            hits = [c for c, n in names.items() if n and name.replace(" ", "").startswith(n.replace(" ", ""))]
        if len(hits) == 1 and hits[0] not in limits:
            limits[hits[0]] = mg
    return limits


_CONTENT_DOSE_RE = re.compile(r'([\d,]+(?:\.\d+)?)\s*(mg|밀리그램|㎎)(?![A-Za-z/])')


def _cites_higher_dose(content: str | None, limit_mg: float) -> bool:
    """단일제 규칙 원문에 상한보다 큰 용량이 적혀 있으면 적응증마다 기준이 다른 규칙이다(리바록사반: 심방세동 20mg,
    정맥혈전증 치료 30mg). 사용자의 적응증을 모르니 판정하지 않는다."""
    return any(float(n.replace(",", "")) > limit_mg for n, _ in _CONTENT_DOSE_RE.findall(content or ""))


def dose_rules_from_ingredient(items: Iterable[dict]) -> dict[tuple[str, str, str, str], dict]:
    """DUR 성분정보 용량주의 행 → {(성분코드, 함께 든 성분코드들, 제형, MAX_QTY): 규칙 값}.

    `MIX_INGR`가 비어 있으면 단일제 규칙(그 성분의 하루 최대량), 있으면 그 조성의 복합제에만 해당하는 규칙이다.
    `limits_mg`는 {성분코드: 하루 최대 mg} — 기준을 못 읽으면 None이고 판정에 쓰지 않는다(원문은 남긴다)."""
    rules: dict[tuple[str, str, str, str], dict] = {}
    for item in _active_rows(items):
        code = _clean(item.get("INGR_CODE"))
        max_qty = _clean(item.get("MAX_QTY"))
        if not code or not max_qty:
            continue
        mix = {c: n.strip() for c, n in _MIX_INGR_RE.findall(item.get("MIX_INGR") or "") if c != code}
        mix_codes = ",".join(sorted(mix))
        form = _clean(item.get("FORM_NAME")) or ""
        kor = _clean(item.get("INGR_NAME"))
        content = _clean_text(item.get("PROHBT_CONTENT"))
        parts = parse_max_qty(max_qty)
        limits = (_dose_limits(code, kor, mix, parts) or None) if parts else None
        if limits and not mix and _cites_higher_dose(content, limits[code]):
            limits = None
        key = (code, mix_codes, form, max_qty)
        rule = rules.setdefault(key, {"ingr_kor": kor, "limits_mg": limits, "contents": [], "remarks": []})
        rule["contents"].append(content)
        rule["remarks"].append(_clean_text(item.get("REMARK")))
    return {
        key: {
            "ingr_kor": r["ingr_kor"], "limits_mg": r["limits_mg"],
            "prohibit_content": _join_unique(r["contents"], "\n"), "remark": _join_unique(r["remarks"], " / "),
        }
        for key, r in rules.items()
    }


def _parse_iso_date(value: str | None) -> date | None:
    """'YYYY-MM-DD'. 형식이 다르면 None."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def hira_item_gen_codes_from_rows(rows: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """심평원 의약품표준코드 CSV 행(포장 단위) → {(품목기준코드, 일반명코드): 값}.
    일반명코드가 빈 행(한약재·취소 품목 다수)은 버린다. 같은 (품목, 코드)의 포장 중 하나라도 취소되지 않았으면
    `cancelled_on`=None, 모두 취소됐으면 가장 늦은 취소일."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        seq, gen = _clean(r.get("품목기준코드")), _clean(r.get("일반명코드(성분명코드)"))
        if not seq or not gen:
            continue
        cancelled = _parse_iso_date(_clean(r.get("취소일자")))
        cur = out.get((seq, gen))
        if cur is None:
            out[(seq, gen)] = {
                "etc_otc": _clean(r.get("전문일반구분")), "atc_code": _clean(r.get("국제표준코드(ATC코드)")),
                "cancelled_on": cancelled, "_live": cancelled is None,
            }
            continue
        cur["etc_otc"] = cur["etc_otc"] or _clean(r.get("전문일반구분"))
        cur["atc_code"] = cur["atc_code"] or _clean(r.get("국제표준코드(ATC코드)"))
        if cancelled is None:
            cur["_live"] = True
        elif cur["cancelled_on"] is None or cancelled > cur["cancelled_on"]:
            cur["cancelled_on"] = cancelled
    for v in out.values():
        if v.pop("_live"):
            v["cancelled_on"] = None
    return out


def hira_gen_codes_from_rows(rows: Iterable[dict]) -> dict[tuple[str], dict]:
    """심평원 의약품주성분 CSV 행 → {(일반명코드,): 제형·투여경로·분류}. 원본은 성분 행마다 같은 값을 되풀이하므로
    일반명코드마다 비어 있지 않은 첫 값을 쓴다."""
    out: dict[tuple[str], dict] = {}
    for r in rows:
        gen, name = _clean(r.get("일반명코드")), _clean(r.get("일반명"))
        if not gen or not name:  # 성분 행과 같은 기준 — 성분이 하나도 없는 코드는 만들지 않는다
            continue
        cur = out.setdefault((gen,), {"form_code": None, "form_name": None, "route": None, "class_no": None})
        for col, src in (("form_code", "제형구분코드"), ("form_name", "제형"), ("route", "투여"), ("class_no", "분류번호")):
            cur[col] = cur[col] or _clean(r.get(src))
    return out


def hira_gen_ingredients_from_rows(rows: Iterable[dict]) -> dict[tuple[str, int], dict]:
    """심평원 의약품주성분 CSV 행 → {(일반명코드, 순번): 값}. 복합제는 성분별 행이 원본 순서대로 1, 2, …"""
    out: dict[tuple[str, int], dict] = {}
    counts: dict[str, int] = {}
    for r in rows:
        gen, name = _clean(r.get("일반명코드")), _clean(r.get("일반명"))
        if not gen or not name:
            continue
        counts[gen] = counts.get(gen, 0) + 1
        out[(gen, counts[gen])] = {
            "ingr_name": name, "strength": _clean(r.get("함량")), "unit": _clean(r.get("단위")),
        }
    return out


# 심평원 영문 일반명에서만 떼는 염·수화물 표기 (DUR 쪽 이름은 떼지 않는다 — 모르핀/모르핀황산염처럼
# DUR이 염별로 코드를 따로 두는 경우가 있어, 양쪽을 떼면 다른 염 코드까지 붙는다)
_SALT_WORDS = frozenset({
    "hydrochloride", "hcl", "dihydrochloride", "hydrobromide", "sodium", "disodium", "potassium", "calcium",
    "magnesium", "mesylate", "mesilate", "dimesylate", "maleate", "fumarate", "hemifumarate", "succinate",
    "tartrate", "bitartrate", "citrate", "besylate", "besilate", "sulfate", "sulphate", "bisulfate",
    "phosphate", "diphosphate", "acetate", "bromide", "nitrate", "lactate", "gluconate", "tosylate",
    "napadisilate", "malate", "oxalate", "pamoate", "embonate", "camsylate", "esylate", "xinafoate",
    "propionate", "dipropionate", "valerate", "butyrate", "furoate", "hydrate", "monohydrate", "dihydrate",
    "trihydrate", "sesquihydrate", "hemihydrate", "anhydrous", "micronized", "arginine", "lysine",
    "tromethamine", "meglumine", "trometamol", "salt", "ester", "hyclate", "monosodium", "dipotassium",
    # 제형 설명어 — 'acetaminophen(encapsulated)'(타이레놀8시간이알서방정)·'aspirin(enteric coated)'·
    # 'calcium carbonate(precipitated)'. 함량은 유효성분 기준 그대로다('enteric coated 215mg'처럼 숫자가 붙으면 남아서 안 맞는다)
    "encapsulated", "enteric", "coated", "precipitated", "usp",
})
_AS_PART_RE = re.compile(r'\(as ([^)]*)\)')


def resolve_hira_components(
    names: Sequence[str], by_eng: Mapping[str, set[str]], mix_type: Mapping[str, str | None],
) -> tuple[set[str], int] | None:
    """심평원 일반명코드의 성분 이름들(영문) → (DUR 성분코드 집합, 단계). 하나라도 못 맞추면 None
    (복합제는 전 성분이 맞아야 해소로 친다). 모두 정규화 후 **완전 일치**만 쓴다(부분 일치는 오매칭 — 우레아→히드록시우레아).
    1단계: 이름 그대로, 또는 '(as X)'의 X가 DUR 영문명과 같음. 2단계: 심평원 이름에서 염·수화물 낱말을 뗀 것이
    DUR 영문명과 같음. 성분이 하나뿐이면 같은 이름의 '복합' 코드는 빼고 '단일' 코드를 쓴다."""
    codes: set[str] = set()
    stage = 1
    for name in names:
        key = norm_ingr_eng(name)
        m = _AS_PART_RE.search(name)
        hit = by_eng.get(key or "") or (by_eng.get(norm_ingr_eng(m.group(1)) or "") if m else None)
        if not hit and key:
            stripped = " ".join(t for t in re.sub(r'[(),]', ' ', _AS_PART_RE.sub(' ', key)).split()
                                if t not in _SALT_WORDS)
            hit = by_eng.get(stripped) if stripped else None
            stage = 2 if hit else stage
        if not hit:
            return None
        if len(names) == 1:
            hit = {c for c in hit if mix_type.get(c) == "단일"} or hit
        codes |= hit
    return codes, stage


_HIRA_UNIT_MG = {"mg": 1.0, "g": 1000.0, "㎍": 0.001, "μg": 0.001, "µg": 0.001, "mcg": 0.001}
# 1회 복용량을 '개수'로 셀 수 있는 내복 제형만 — 현탁액용정제는 녹여 나눠 먹어 개수가 아니다
_UNIT_DOSE_FORM_RE = re.compile(r'정|캡슐')


def hira_amount_mg(strength: str | None, unit: str | None, form_name: str | None) -> float | None:
    """심평원 주성분 함량 → 정·캡슐 1개당 mg. 질량 단위가 아니거나('mg(1mg/mL)', 'I.U', 'mg/정(야간용)')
    정·캡슐이 아닌 제형이면 None. '(as 암로디핀)'이 붙은 성분은 함량도 그 유효성분 기준으로 적혀 있다."""
    factor = _HIRA_UNIT_MG.get((unit or "").strip())
    form = form_name or ""
    if factor is None or not _UNIT_DOSE_FORM_RE.search(form) or "현탁" in form:
        return None
    try:
        value = float((strength or "").replace(",", ""))
    except ValueError:
        return None
    return value * factor if value > 0 else None


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


_PAREN_TEXT_RE = re.compile(r'[\(\[（]([^\)\]）]+)[\)\]）]')


def candidate_ingredient_names(
    ingr_name: list[dict | None] | None, main_item_ingr: str | None, item_name: str | None,
) -> list[str]:
    """약 하나의 성분명 후보를 세 군데서 모은다(중복 가능, 순서 유지).

    1. `ingr_name` JSONB 의 kor
    2. `main_item_ingr` 의 `[Mxxxx]성분명` 파싱 결과
    3. `item_name` 괄호 안 텍스트 — 외용제(겔·플라스타 등)는 식약처가 DUR 성분코드를 안 붙여 병용금기 원본에
       INGR_CODE 가 NULL 로 오는 경우가 많은데, 제품명 '뉴펜겔(케토프로펜)'처럼 괄호에 성분명이 노출된다."""
    names = [item["kor"] for item in ingr_name or [] if item and item.get("kor")]
    names += [item["kor"] for item in _parse_main_ingr(main_item_ingr or "") if item.get("kor")]
    for paren in _PAREN_TEXT_RE.findall(item_name or ""):
        names += [part.strip() for part in re.split(r"[,/·]", paren) if part.strip()]
    return names


def make_ingredient_resolver(pairs: Iterable[Sequence[str | None]]) -> Callable[[str], str | None]:
    """`(성분명, DUR 성분코드)` 쌍에서 "성분명 → 코드" 해소 함수를 만든다. 같은 이름이 여러 번 오면 앞의 것을 쓴다.

    정규화한 이름이 완전히 같으면 그 코드, 아니면 접두(염 형태 차이: '트리메부틴' ↔
    '트리메부틴말레산염')가 맞는 코드 중 가장 긴 이름의 것. substring 매칭은 '우레아→히드록시우레아' 같은
    오매칭이 나서 쓰지 않는다. 접두가 맞아도 남는 부분이 다른 성분을 가리키면 버린다(`_is_form_rest`) —
    '포비돈'→포비돈요오드, '미분화'→미분화 시클레소니드, '니코틴산아미드'→니코틴 같은 오매칭이 실제로 있었다.
    `pairs`에는 DUR이 직접 준 이름만 넣어야 한다 — 이 함수가 맺은 행까지 넣으면 한 번 잘못 맺은 이름이 다음 매칭의 기준이 된다."""
    name_to_code: dict[str, str] = {}
    for ingr_kor, ingr_code in pairs:
        if not ingr_kor or not ingr_code:
            continue
        key = _make_drug_key(ingr_kor)
        if key and key not in name_to_code:
            name_to_code[key] = ingr_code
    code_keys = sorted(name_to_code, key=len, reverse=True)
    other_names = [k for k in name_to_code if len(k) >= 3]

    def _is_form_rest(rest: str) -> bool:
        if rest.endswith(_FORM_REST_SUFFIXES):  # 염·수화물·용매화물·엑스 — '에스암로디핀' + '니코틴산염'
            return True
        # '산'·'아미드'가 붙으면 다른 화합물이다(니코틴 → 니코틴산 → 니코틴산아미드)
        return not rest.startswith(("산", "아미드")) and not any(name in rest for name in other_names)

    def _resolve(cand: str) -> str | None:
        key = _make_drug_key(cand)
        if len(key) < 3:
            return None
        code = name_to_code.get(key)
        if code:
            return code
        for ck in code_keys:
            if key.startswith(ck):
                rest = key[len(ck):]
            elif ck.startswith(key):
                rest = ck[len(key):]
            else:
                continue
            if _is_form_rest(rest):
                return name_to_code[ck]
        return None

    return _resolve


_FORM_REST_SUFFIXES = ("염", "수화물", "설폭시드", "에탄올레이트", "엑스")


def clean_html_text(value: str | None) -> str:
    """CDATA 안에 날것으로 남은 HTML 엔티티(`&nbsp;`·`&amp;` 등)를 풀고 공백을 하나로 정리한다.
    허가정보 원문에 '2)&nbsp;고지단백혈증'처럼 엔티티가 그대로 들어 있어 풀지 않으면 화면에 그대로 보인다."""
    return " ".join(html.unescape(value or "").split())


def permit_doc_to_text(doc_xml: str | None) -> str | None:
    """허가정보 상세의 `EE/UD/NB_DOC_DATA`(CDATA가 든 XML) → 읽을 수 있는 평문(전문).

    SECTION/ARTICLE 제목은 한 줄, PARAGRAPH는 그 아래 줄로 낸다. 자르지 않는다 — 화면은 앱의
    "더보기"가 접고, AI 프롬프트는 쓰는 쪽(`ai_guide_service`)이 필드당 상한으로 자른다.
    XML이 깨져 있으면 태그만 걷어낸 텍스트로 폴백."""
    if not doc_xml or not doc_xml.strip():
        return None
    blocks: list[list[str]] = []
    try:
        root = ET.fromstring(doc_xml.strip())
        for el in root.iter():
            if el.tag in ("SECTION", "ARTICLE"):
                title = clean_html_text(el.get("title"))
                if title:
                    blocks.append([title])
            elif el.tag == "PARAGRAPH":
                line = clean_html_text(el.text)
                if line:
                    if not blocks:
                        blocks.append([])
                    blocks[-1].append(line)
    except ET.ParseError:
        plain = clean_html_text(re.sub(r"<[^>]+>", " ", doc_xml))
        blocks = [[plain]] if plain else []

    texts = ["\n".join(b) for b in blocks if b]
    if not texts:
        return None
    return "\n".join(texts)
