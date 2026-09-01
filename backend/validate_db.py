"""
통합 DB 데이터 품질 검증 스크립트

사용법:
    docker exec -it drugtest-backend-1 python validate_db.py
"""
import asyncio

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

SEP = "=" * 50


async def validate():
    async with AsyncSessionLocal() as db:

        print(f"\n{SEP}\n1. 기본 현황\n{SEP}")
        row = (await db.execute(text("""
            SELECT
                (SELECT count(*) FROM drugs) AS total_drugs,
                (SELECT count(*) FROM drugs WHERE efcy_qesitm IS NOT NULL) AS has_efcy,
                (SELECT count(*) FROM drugs WHERE ingr_name IS NOT NULL) AS has_ingr,
                (SELECT count(*) FROM drugs WHERE drug_shape IS NOT NULL) AS has_shape,
                (SELECT count(*) FROM drug_ingredients) AS di_rows,
                (SELECT count(*) FROM drug_ingredients WHERE source = 'dur') AS di_dur,
                (SELECT count(*) FROM drug_ingredients WHERE source = 'jsonb_fallback') AS di_fb,
                (SELECT count(DISTINCT drug_id) FROM drug_ingredients WHERE ingr_code IS NOT NULL) AS di_drugs,
                (SELECT count(*) FROM dur_ingredient_contraindications) AS contra,
                (SELECT count(*) FROM dur_ingredient_contraindications WHERE risk_tags IS NOT NULL) AS contra_tagged,
                (SELECT count(*) FROM dur_ingredient_effect_groups) AS effect,
                (SELECT count(*) FROM residual_interactions) AS residual
        """))).fetchone()
        resolve_pct = row.di_drugs / row.total_drugs * 100 if row.total_drugs else 0
        print(f"  drugs 전체:               {row.total_drugs:>8,}건")
        print(f"  └ 효능정보(efcy):         {row.has_efcy:>8,}건")
        print(f"  └ 성분JSONB(ingr):        {row.has_ingr:>8,}건")
        print(f"  └ 낱알식별(shape):        {row.has_shape:>8,}건")
        print(f"  drug_ingredients:         {row.di_rows:>8,}건  (dur={row.di_dur:,} / fallback={row.di_fb:,})")
        print(f"  └ 성분코드 해소 약품:     {row.di_drugs:>8,}건 ({resolve_pct:.1f}%)")
        print(f"  성분 병용금기 규칙:       {row.contra:>8,}건  (risk_tags {row.contra_tagged:,}건)")
        print(f"  성분 효능군중복 규칙:     {row.effect:>8,}건")
        print(f"  residual_interactions:    {row.residual:>8,}건")

        print(f"\n{SEP}\n2. 성분 규칙 이상 데이터\n{SEP}")

        self_cnt = (await db.execute(text(
            "SELECT count(*) FROM dur_ingredient_contraindications WHERE ingr_code_a = ingr_code_b"
        ))).scalar()
        print(f"  자기 자신 성분쌍:         {self_cnt:>8,}건  {'✅' if self_cnt == 0 else '❌ 문제'}")

        unordered = (await db.execute(text(
            "SELECT count(*) FROM dur_ingredient_contraindications WHERE ingr_code_a > ingr_code_b"
        ))).scalar()
        print(f"  정규순서 위반(a>b):       {unordered:>8,}건  {'✅' if unordered == 0 else '❌ 문제'}")

        dup = (await db.execute(text("""
            SELECT count(*) FROM (
                SELECT ingr_code_a, ingr_code_b FROM dur_ingredient_contraindications
                GROUP BY 1, 2 HAVING count(*) > 1
            ) t
        """))).scalar()
        print(f"  중복 성분쌍:              {dup:>8,}건  {'✅' if dup == 0 else '❌ 문제'}")

        derived = (await db.execute(text(
            "SELECT count(*) FROM dur_ingredient_contraindications WHERE remark LIKE 'derived%'"
        ))).scalar()
        print(f"  품목쌍에서 합성된 규칙:   {derived:>8,}건  (remark='derived-from-product')")

        orphan = (await db.execute(text("""
            SELECT count(*) FROM drug_ingredients di
            LEFT JOIN drugs d ON d.id = di.drug_id WHERE d.id IS NULL
        """))).scalar()
        print(f"  drug_ingredients 고아행:  {orphan:>8,}건  {'✅' if orphan == 0 else '❌ 문제'}")

        print(f"\n{SEP}\n3. drugs 테이블 이상 데이터\n{SEP}")

        dur_auto = (await db.execute(text(
            "SELECT count(*) FROM drugs WHERE item_seq LIKE 'DUR_%'"
        ))).scalar()
        print(f"  DUR 자동생성(비정상 seq): {dur_auto:>6,}건  {'✅' if dur_auto == 0 else '⚠️ 확인 필요'}")

        dup_key = (await db.execute(text("""
            SELECT count(*) FROM (
                SELECT drug_key FROM drugs WHERE drug_key IS NOT NULL
                GROUP BY drug_key HAVING count(*) > 1
            ) t
        """))).scalar()
        print(f"  drug_key 중복:            {dup_key:>8,}건  {'⚠️' if dup_key else '✅'}")

        print(f"\n{SEP}\n4. 알려진 병용금기 쌍 — 성분 경로로 탐지되나 (샘플)\n{SEP}")

        # (약품명 A 포함) 제품의 성분코드 × (약품명 B 포함) 제품의 성분코드가
        # dur_ingredient_contraindications 규칙에 있는지 확인
        known_pairs = [
            ("이트라코나졸", "심바스타틴"),
            ("사이클로스포린", "아토르바스타틴"),
            ("메토트렉세이트", "피록시캄"),
        ]
        for a, b in known_pairs:
            hit = (await db.execute(text("""
                SELECT c.prohibit_content, c.remark
                FROM drugs da
                JOIN drug_ingredients ia ON ia.drug_id = da.id AND ia.ingr_code IS NOT NULL
                JOIN drugs db2 ON db2.item_name ILIKE :b
                JOIN drug_ingredients ib ON ib.drug_id = db2.id AND ib.ingr_code IS NOT NULL
                JOIN dur_ingredient_contraindications c
                  ON (c.ingr_code_a = ia.ingr_code AND c.ingr_code_b = ib.ingr_code)
                  OR (c.ingr_code_a = ib.ingr_code AND c.ingr_code_b = ia.ingr_code)
                WHERE da.item_name ILIKE :a
                LIMIT 1
            """), {"a": f"%{a}%", "b": f"%{b}%"})).fetchone()
            if hit:
                note = hit.prohibit_content or hit.remark or ""
                print(f"  {a} + {b}: ✅ {note[:44]}")
            else:
                print(f"  {a} + {b}: ❌ 규칙 없음")


asyncio.run(validate())
