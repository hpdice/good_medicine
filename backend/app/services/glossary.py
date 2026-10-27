"""AI 설명에 근거로 넣는 의학 용어 풀이집.

AI가 용어를 제 지식으로 풀이하면 근거 없는 증상·기전이 섞이므로, 풀이는 출처를 확인한 문구만
프롬프트의 [용어 풀이]로 넘기고 모델은 그 범위 안에서만 쓰게 한다. 항목은 공신력 있는 기관 페이지의
원문을 직접 확인해 쉬운 말로 옮긴 것이며(확인일 2026-10-27), 출처 없는 용어는 넣지 않는다 — 풀이가
없는 용어는 모델이 풀이하지 않고 원문 그대로 쓴다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    aliases: tuple[str, ...]  # 공백·대소문자 무시하고 부분 일치로 찾는다
    definition: str
    source: str
    url: str


GLOSSARY: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        term="횡문근융해증",
        aliases=("횡문근융해",),
        definition=(
            "근육이 심하게 손상돼 죽고, 그때 생긴 독성 물질이 혈액으로 들어가는 상태입니다. "
            "근육통·뻣뻣함·힘 빠짐이 나타나고 소변이 붉은색이나 갈색으로 변할 수 있으며, "
            "급성 신부전이 생기는 경우가 많습니다."
        ),
        source="서울아산병원 질환백과",
        url="https://www.amc.seoul.kr/asan/healthinfo/disease/diseaseDetail.do?contentId=32313",
    ),
    GlossaryEntry(
        term="QT 연장",
        aliases=("QT연장", "QTc연장", "QT간격연장", "긴QT"),
        definition=(
            "심전도에서 QT 간격이 길어지는, 심장 전기 활동의 이상입니다. 위험한 심장 박동과 "
            "돌연사의 위험이 커집니다. 평소엔 증상이 없다가 위험한 빠른 박동이 생기면 "
            "두근거림·어지러움·실신이 나타날 수 있습니다."
        ),
        source="MSD 매뉴얼 일반인용 - 긴 QT 간격 증후군",
        url=(
            "https://www.msdmanuals.com/ko/home/%EC%8B%AC%EC%9E%A5-%EB%B0%8F-%ED%98%88%EA%B4%80-"
            "%EC%9E%A5%EC%95%A0/%EC%9D%B4%EC%83%81-%EC%8B%AC%EC%9E%A5-%EB%B0%95%EB%8F%99/"
            "%EA%B8%B4-qt-%EA%B0%84%EA%B2%A9-%EC%A6%9D%ED%9B%84%EA%B5%B0"
        ),
    ),
    GlossaryEntry(
        term="토르사드 드 푸앵트",
        aliases=("TorsadedePointes", "TorsadesdePointes", "토르사드", "염전성심실빈맥"),
        definition=(
            "염전성 심실빈맥이라고도 하는, 빠르고 위험한 심장 박동입니다. "
            "심장이 박동을 멈추는 심실세동으로 바뀌어 생명을 위협할 수 있습니다."
        ),
        source="MSD 매뉴얼 일반인용 - 긴 QT 간격 증후군",
        url=(
            "https://www.msdmanuals.com/ko/home/%EC%8B%AC%EC%9E%A5-%EB%B0%8F-%ED%98%88%EA%B4%80-"
            "%EC%9E%A5%EC%95%A0/%EC%9D%B4%EC%83%81-%EC%8B%AC%EC%9E%A5-%EB%B0%95%EB%8F%99/"
            "%EA%B8%B4-qt-%EA%B0%84%EA%B2%A9-%EC%A6%9D%ED%9B%84%EA%B5%B0"
        ),
    ),
    GlossaryEntry(
        term="부정맥",
        aliases=("부정맥",),
        definition=(
            "심장이 정상적인 전기 자극대로 뛰지 않고 불규칙하거나 비정상적으로 빠르거나 "
            "느리게 뛰는 상태입니다. 심하면 심정지가 올 수 있고, 특히 심실에서 생기는 "
            "부정맥은 더 위험할 수 있습니다."
        ),
        source="질병관리청 국가건강정보포털 - 부정맥",
        url=(
            "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/"
            "gnrlzHealthInfoView.do?cntnts_sn=1102"
        ),
    ),
    GlossaryEntry(
        term="혈중농도",
        aliases=("혈중농도",),
        definition=(
            "혈액 속에 들어 있는 약물 같은 성분의 농도입니다. 혈중농도가 올라간다는 것은 "
            "혈액 속에 그 성분이 더 많이 들어 있게 된다는 뜻입니다."
        ),
        source="서울아산병원 쉬운 의학용어 - 혈중농도",
        url="https://www.amc.seoul.kr/asan/healthinfo/easymediterm/easyMediTermDetail.do?dictId=4803",
    ),
    GlossaryEntry(
        term="세로토닌 증후군",
        aliases=("세로토닌증후군",),
        definition=(
            "약물 때문에 뇌의 세로토닌 수용체가 지나치게 자극돼 생기는, 생명을 위협할 수 있는 "
            "약물 반응입니다. 체온이 오르고 근육이 떨리거나 굳으며, 불안·초조와 혼란(섬망)이 "
            "나타날 수 있습니다."
        ),
        source="MSD 매뉴얼 일반인용 - 세로토닌 증후군",
        url="https://www.msdmanuals.com/ko/home/부상-및-중독/열중증/세로토닌-증후군",
    ),
)


def _squash(text: str) -> str:
    return "".join(text.split()).lower()


def find_entries(text: str) -> list[GlossaryEntry]:
    """text에 나오는 용어의 풀이를 용어집 순서대로 돌려준다(같은 항목은 한 번만)."""
    squashed = _squash(text)
    return [
        entry
        for entry in GLOSSARY
        if any(_squash(alias) in squashed for alias in (entry.term, *entry.aliases))
    ]
