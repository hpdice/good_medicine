import pytest

from app.services.glossary import GLOSSARY, find_entries


@pytest.mark.parametrize(
    ("text", "terms"),
    [
        ("근병증, 횡문근융해의 위험증가", ["횡문근융해증"]),
        ("횡문근융해증 위험", ["횡문근융해증"]),
        ("QTc 연장 효과 증대로 심각한 위험(Torsade de Pointes)", ["QT 연장", "토르사드 드 푸앵트"]),
        ("QT 간격 연장, 심실성 부정맥", ["QT 연장", "부정맥"]),
        ("Torsade de pointes 위험", ["토르사드 드 푸앵트"]),  # 대소문자·공백 무시
        ("고혈압위기, 세로토닌증후군 발생 위험 증가", ["세로토닌 증후군"]),
        ("리바록사반의 혈중농도가 상승하여 출혈위험 증가", ["혈중농도"]),
        ("출혈위험 증가", []),  # 출처 있는 풀이가 없는 용어는 찾지 않는다
        ("", []),
    ],
)
def test_find_entries(text, terms):
    assert [e.term for e in find_entries(text)] == terms


def test_every_entry_has_source_and_complete_definition():
    # 출처 없는 풀이를 넣지 않는다는 원칙이 항목 구조에서 깨지지 않게
    for entry in GLOSSARY:
        assert entry.source and entry.url.startswith("https://"), entry.term
        assert entry.definition.endswith("."), entry.term
        assert entry.aliases, entry.term
