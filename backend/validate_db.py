"""
통합 DB 데이터 품질 검증 스크립트

사용법:
    docker exec -it drugtest-backend-1 python validate_db.py
"""
import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

SEP = "=" * 50


async def validate():
    async with AsyncSessionLocal() as db:

        print(f"\n{SEP}")
        print("1. 기본 현황")
        print(SEP)
        r = await db.execute(text("""
            SELECT
                (SELECT count(*) FROM drugs) AS total_drugs,
                (SELECT count(*) FROM drugs WHERE efcy_qesitm IS NOT NULL) AS has_efcy,
                (SELECT count(*) FROM drugs WHERE ingr_name IS NOT NULL) AS has_ingr,
                (SELECT count(*) FROM drugs WHERE drug_shape IS NOT NULL) AS has_shape,
                (SELECT count(*) FROM drug_interactions) AS total_interactions
        """))
        row = r.fetchone()
        print(f"  drugs 전체:          {row.total_drugs:>8,}건")
        print(f"  └ 효능정보(efcy):    {row.has_efcy:>8,}건")
        print(f"  └ 성분JSONB(ingr):   {row.has_ingr:>8,}건")
        print(f"  └ 낱알식별(shape):   {row.has_shape:>8,}건")
        print(f"  drug_interactions:   {row.total_interactions:>8,}건")

        print(f"\n{SEP}")
        print("2. drug_interactions 이상 데이터")
        print(SEP)

        r = await db.execute(text(
            "SELECT count(*) FROM drug_interactions WHERE drug1_id = drug2_id"
        ))
        self_cnt = r.scalar()
        print(f"  자기 자신 상호작용:  {self_cnt:>8,}건  {'✅' if self_cnt == 0 else '❌ 문제'}")

        r = await db.execute(text("""
            SELECT
                count(*) FILTER (WHERE mechanism IS NULL OR mechanism = '') AS no_mechanism,
                count(*) AS total
            FROM drug_interactions
        """))
        row = r.fetchone()
        pct = row.no_mechanism / row.total * 100 if row.total > 0 else 0
        print(f"  mechanism 없음:      {row.no_mechanism:>8,}건  ({pct:.1f}%)")

        r = await db.execute(text("""
            SELECT count(*) FROM (
                SELECT drug1_id, drug2_id, interaction_type, count(*)
                FROM drug_interactions
                GROUP BY drug1_id, drug2_id, interaction_type
                HAVING count(*) > 1
            ) t
        """))
        dup_cnt = r.scalar()
        print(f"  중복 쌍:             {dup_cnt:>8,}건  {'✅' if dup_cnt == 0 else '❌ 문제'}")

        print(f"\n{SEP}")
        print("3. drugs 테이블 이상 데이터")
        print(SEP)

        r = await db.execute(text(
            "SELECT count(*) FROM drugs WHERE item_seq LIKE 'DUR_%'"
        ))
        dur_auto = r.scalar()
        print(f"  DUR 자동생성(비정상 seq): {dur_auto:>6,}건  {'✅' if dur_auto == 0 else '⚠️ 확인 필요'}")

        r = await db.execute(text("""
            SELECT count(*) FROM (
                SELECT drug_key, count(*)
                FROM drugs
                WHERE drug_key IS NOT NULL
                GROUP BY drug_key
                HAVING count(*) > 1
            ) t
        """))
        dup_key = r.scalar()
        print(f"  drug_key 중복:       {dup_key:>8,}건  {'✅' if dup_key == 0 else '⚠️ 확인 필요'}")

        r = await db.execute(text(
            "SELECT count(*) FROM drugs WHERE length(item_name) < 3"
        ))
        short_name = r.scalar()
        print(f"  item_name 3자 미만:  {short_name:>8,}건  {'✅' if short_name == 0 else '⚠️ 확인 필요'}")

        print(f"\n{SEP}")
        print("4. 알려진 약품 쌍 검증 (샘플)")
        print(SEP)

        known_pairs = [
            ("와파린", "아스피린"),
            ("이트라코나졸", "심바스타틴"),
            ("사이클로스포린", "아토르바스타틴"),
        ]
        for a, b in known_pairs:
            r = await db.execute(text("""
                SELECT di.mechanism
                FROM drug_interactions di
                JOIN drugs d1 ON di.drug1_id = d1.id
                JOIN drugs d2 ON di.drug2_id = d2.id
                WHERE d1.item_name ILIKE :a AND d2.item_name ILIKE :b
                LIMIT 1
            """), {"a": f"%{a}%", "b": f"%{b}%"})
            row = r.fetchone()
            status = f"✅ {row.mechanism[:40]}" if row else "❌ 없음"
            print(f"  {a} + {b}: {status}")


asyncio.run(validate())
