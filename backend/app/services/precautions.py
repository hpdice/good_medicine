"""허가사항 '사용상의 주의사항' 원문을 화면용으로 줄인다.

허가사항 전문(`drugs.atpn_qesitm`)은 의·약사용이라 임상시험 결과표·과량투여 처치 같은 항목까지 길게 들어 있다(테라펜정 약 1만 9천 자).
앱 화면에 내려 주는 값에서만 이런 항목을 뺀다 — DB 원문은 그대로 두므로 건강 상태 금기 판정(`condition_taboo`)과
AI 설명 근거는 전문을 계속 쓴다. 항목 제목이 알려진 형식("1. 경고", "4.1. 임상시험 자료")일 때만 자르고,
형식을 못 알아보면 원문을 그대로 돌려준다.
"""
import re

_TOP_RE = re.compile(r"^\s*(\d{1,2})\.\s+(\S.*)$")  # "4. 이상반응"
_SUB_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.?\s+(\S.*)$")  # "4.1. 임상시험 자료"

# 사용자가 복용 판단에 쓰지 않는 항목(제목에 들어 있으면 뺀다). 경고·금기·신중 투여·일반적 주의·상호작용·임부·소아·고령자·운전은 남긴다.
_DROP_TOP_TITLES = ("과량투여", "의약품동등성시험", "임상검사치", "약동학", "약리작용", "임상시험", "전문가를위한정보")
_DROP_TOP_EXACT = ("기타",)
_DROP_SUB_TITLES = ("임상시험",)  # 이상반응 아래 "4.1. 임상시험 자료"(위약 대조 시험 결과표)


def _norm(title: str) -> str:
    return re.sub(r"[\s.,·ㆍ()]", "", title)


def _drop_top(title: str) -> bool:
    t = _norm(title)
    return t in _DROP_TOP_EXACT or any(k in t for k in _DROP_TOP_TITLES)


def _drop_sub(title: str) -> bool:
    return any(k in _norm(title) for k in _DROP_SUB_TITLES)


def trim_precautions_for_display(text: str | None) -> str | None:
    """임상시험 결과 등 사용자에게 필요 없는 항목을 뺀 주의사항. 뺄 게 없거나 형식을 못 알아보면 원문 그대로."""
    if not text:
        return text

    # 1) 줄을 (머리 | 항목 | 하위 항목) 블록으로 나눈다
    blocks: list[dict] = [{"kind": "pre", "title": "", "lines": []}]
    for line in text.split("\n"):
        sub, top = _SUB_RE.match(line), _TOP_RE.match(line)
        if sub:
            blocks.append({"kind": "sub", "num": (int(sub[1]), int(sub[2])), "title": sub[3], "lines": []})
        elif top:
            blocks.append({"kind": "top", "num": (int(top[1]), 0), "title": top[2], "lines": []})
        else:
            blocks[-1]["lines"].append(line)

    # 2) 뺄 블록을 정한다 — 뺀 항목의 하위 항목·본문도 함께
    dropped_any = False
    top_dropped = False
    for b in blocks:
        if b["kind"] == "top":
            top_dropped = _drop_top(b["title"])
            b["drop"] = top_dropped
        elif b["kind"] == "sub":
            b["drop"] = top_dropped or _drop_sub(b["title"])
        else:
            b["drop"] = False
        dropped_any = dropped_any or b["drop"]
    if not dropped_any:
        return text

    # 3) 번호가 1부터 빠짐없이 이어지는 문서만 번호를 다시 매긴다(구멍이 남아 "9. … 12. …"로 읽히지 않게)
    tops = [b for b in blocks if b["kind"] == "top"]
    renumber = [b["num"][0] for b in tops] == list(range(1, len(tops) + 1))
    out: list[str] = []
    top_no = 0
    sub_no = 0
    sub_ok = False
    for idx, b in enumerate(blocks):
        if b["drop"]:
            continue
        if b["kind"] == "top":
            top_no += 1
            sub_no = 0
            following = []
            for nb in blocks[idx + 1:]:
                if nb["kind"] == "top":
                    break
                if nb["kind"] == "sub":
                    following.append(nb["num"])
            sub_ok = [n[1] for n in following] == list(range(1, len(following) + 1)) and all(
                n[0] == b["num"][0] for n in following
            )
            out.append(f"{top_no}. {b['title']}" if renumber else f"{b['num'][0]}. {b['title']}")
        elif b["kind"] == "sub":
            sub_no += 1
            if renumber and sub_ok:
                out.append(f"{top_no}.{sub_no}. {b['title']}")
            else:
                out.append(f"{b['num'][0]}.{b['num'][1]}. {b['title']}")
        out.extend(b["lines"])

    result = "\n".join(out).strip()
    return result or text
