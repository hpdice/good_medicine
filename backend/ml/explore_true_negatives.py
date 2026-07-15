"""복합제(하나의 제품에 성분이 2개 이상) 데이터로 '진짜 음성' 후보를 탐색한다.

식약처가 두 성분을 하나의 제품으로 승인했다는 것은, 그 두 성분을 함께
투여해도 된다는 실질적 증거다 (병용금기 성분을 하나의 정제로 묶어
승인하지는 않는다). 이걸 진짜 안전 라벨로 쓸 수 있는지 검증한다.
"""
import asyncio


async def main():
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.drug import Drug
    from app.models.drug_interaction import DrugInteraction

    async with AsyncSessionLocal() as db:
        drug_rows = (await db.execute(
            select(Drug.id, Drug.ingr_name).where(Drug.ingr_name.isnot(None))
        )).all()
        pair_rows = (await db.execute(
            select(DrugInteraction.drug1_id, DrugInteraction.drug2_id)
            .where(DrugInteraction.interaction_type == "contraindicated")
        )).all()

    ingr_by_drug = {}
    for drug_id, ingr_name in drug_rows:
        codes = {item["dur_code"] for item in ingr_name if isinstance(item, dict) and item.get("dur_code")}
        if codes:
            ingr_by_drug[drug_id] = codes

    # 1) 복합제 내부 co-formulated 성분쌍 ("안전 후보")
    safe_ingr_pairs = set()
    for codes in ingr_by_drug.values():
        codes = sorted(codes)
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                safe_ingr_pairs.add((codes[i], codes[j]))
    print(f"복합제 유래 co-formulated 성분쌍: {len(safe_ingr_pairs):,}개")
    print(f"성분 정보 있는 약품: {len(ingr_by_drug):,}개")

    # 2) DUR 병용금기 드러그쌍에서 유도되는 '위험 성분쌍' (양쪽 다 ingr_name 있는 경우만)
    risky_ingr_pairs = set()
    n_both_have_ingr = 0
    for d1, d2 in pair_rows:
        c1, c2 = ingr_by_drug.get(d1), ingr_by_drug.get(d2)
        if not c1 or not c2:
            continue
        n_both_have_ingr += 1
        for x in c1:
            for y in c2:
                if x == y:
                    continue
                risky_ingr_pairs.add(tuple(sorted((x, y))))
    print(f"DUR 유래 위험 성분쌍: {len(risky_ingr_pairs):,}개 (양쪽 다 ingr_name 있는 DUR 쌍 {n_both_have_ingr:,}개에서 유도)")

    # 3) 충돌 검사: 복합제로 같이 팔리는데 DUR상 위험 성분쌍으로도 잡히는 경우가 있는가?
    conflict = safe_ingr_pairs & risky_ingr_pairs
    print(f"\n충돌(복합제인데 DUR 위험쌍으로도 존재): {len(conflict):,}개")
    if conflict:
        for pair in list(conflict)[:10]:
            print("  ", pair)

    print(f"\n순수 안전 후보(충돌 없음): {len(safe_ingr_pairs - conflict):,}개")


asyncio.run(main())
