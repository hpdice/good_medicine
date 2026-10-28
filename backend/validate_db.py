"""
통합 DB 데이터 품질 검증 스크립트

사용법:
    docker exec -it drugtest-backend-1 python validate_db.py

종료 코드: 치명적 문제(❌)가 하나라도 있으면 1 — 월간 자동 갱신(scripts/monthly-sync.ps1)이
품질 게이트로 쓴다. ⚠️ 항목은 경고만 하고 실패로 보지 않는다.
"""
import asyncio
import sys

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

SEP = "=" * 50

# 규칙 수 하한 — 동기화가 규칙을 지우지는 않으므로, 이보다 적으면 DB가 비었거나 잘못 복원된 것.
# (현재: 약품 약 3.5만 · 성분 병용금기 357 · 효능군 259)
MIN_DRUGS = 30_000
MIN_CONTRA_RULES = 300
MIN_EFFECT_RULES = 200

# 개수가 0이어야 정상인 점검 (실패 = 품질 게이트 실패): (표시 이름, 개수를 세는 SQL, 문제 메시지)
MUST_BE_ZERO = [
    ("자기 자신 성분쌍",
     "SELECT count(*) FROM dur_ingredient_contraindications WHERE ingr_code_a = ingr_code_b",
     "자기 자신 성분쌍"),
    ("정규순서 위반(a>b)",
     "SELECT count(*) FROM dur_ingredient_contraindications WHERE ingr_code_a > ingr_code_b",
     "정규순서 위반"),
    ("중복 성분쌍",
     """SELECT count(*) FROM (
            SELECT ingr_code_a, ingr_code_b FROM dur_ingredient_contraindications
            GROUP BY 1, 2 HAVING count(*) > 1
        ) t""",
     "중복 성분쌍"),
    ("drug_ingredients 고아행",
     """SELECT count(*) FROM drug_ingredients di
        LEFT JOIN drugs d ON d.id = di.drug_id WHERE d.id IS NULL""",
     "drug_ingredients 고아행"),
]

# 개수가 0이 아니면 확인만 하라는 점검 (경고, 실패 아님): (표시 이름, SQL, 경고 문구)
WARN_IF_NONZERO = [
    ("DUR 자동생성(비정상 seq)", "SELECT count(*) FROM drugs WHERE item_seq LIKE 'DUR_%'", "확인 필요"),
    ("drug_key 중복",
     """SELECT count(*) FROM (
            SELECT drug_key FROM drugs WHERE drug_key IS NOT NULL
            GROUP BY drug_key HAVING count(*) > 1
        ) t""",
     ""),
]

# 알려진 병용금기 쌍 (약품명 A 포함, 약품명 B 포함) — 성분 경로로 탐지되는지 샘플 확인
KNOWN_PAIRS = [
    ("이트라코나졸", "심바스타틴"),
    ("사이클로스포린", "아토르바스타틴"),
    ("메토트렉세이트", "피록시캄"),
]

# (약품명 A 포함) 제품의 성분코드 × (약품명 B 포함) 제품의 성분코드가 규칙에 있는지
KNOWN_PAIR_SQL = """
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
"""


async def _count(db, sql: str) -> int:
    return (await db.execute(text(sql))).scalar()


async def _overview(db, problems: list[str]) -> None:
    print(f"\n{SEP}\n1. 기본 현황\n{SEP}")
    row = (await db.execute(text("""
        SELECT
            (SELECT count(*) FROM drugs) AS total_drugs,
            (SELECT count(*) FROM drugs WHERE efcy_qesitm IS NOT NULL) AS has_efcy,
            (SELECT count(*) FROM drugs WHERE ingr_name IS NOT NULL) AS has_ingr,
            (SELECT count(*) FROM drug_ingredients) AS di_rows,
            (SELECT count(*) FROM drug_ingredients WHERE source = 'dur') AS di_dur,
            (SELECT count(*) FROM drug_ingredients WHERE source = 'jsonb_fallback') AS di_fb,
            (SELECT count(DISTINCT drug_id) FROM drug_ingredients WHERE ingr_code IS NOT NULL) AS di_drugs,
            (SELECT count(*) FROM dur_ingredient_contraindications) AS contra,
            (SELECT count(*) FROM dur_ingredient_contraindications WHERE risk_tags IS NOT NULL) AS contra_tagged,
            (SELECT count(*) FROM dur_ingredient_effect_groups) AS effect,
            (SELECT count(*) FROM residual_interactions) AS residual
    """))).one()
    resolve_pct = row.di_drugs / row.total_drugs * 100 if row.total_drugs else 0
    print(f"  drugs 전체:               {row.total_drugs:>8,}건")
    print(f"  └ 효능정보(efcy):         {row.has_efcy:>8,}건")
    print(f"  └ 성분JSONB(ingr):        {row.has_ingr:>8,}건")
    print(f"  drug_ingredients:         {row.di_rows:>8,}건  (dur={row.di_dur:,} / fallback={row.di_fb:,})")
    print(f"  └ 성분코드 해소 약품:     {row.di_drugs:>8,}건 ({resolve_pct:.1f}%)")
    print(f"  성분 병용금기 규칙:       {row.contra:>8,}건  (risk_tags {row.contra_tagged:,}건)")
    print(f"  성분 효능군중복 규칙:     {row.effect:>8,}건")
    print(f"  residual_interactions:    {row.residual:>8,}건")
    for label, value, floor in (("약품 수", row.total_drugs, MIN_DRUGS),
                                ("병용금기 규칙", row.contra, MIN_CONTRA_RULES),
                                ("효능군 규칙", row.effect, MIN_EFFECT_RULES)):
        if value < floor:
            problems.append(f"{label} {value:,} < 하한 {floor:,}")


async def _rule_anomalies(db, problems: list[str]) -> None:
    print(f"\n{SEP}\n2. 성분 규칙 이상 데이터\n{SEP}")
    for label, sql, problem in MUST_BE_ZERO:
        count = await _count(db, sql)
        print(f"  {label + ':':<26}{count:>8,}건  {'✅' if count == 0 else '❌ 문제'}")
        if count:
            problems.append(f"{problem} {count}건")
    derived = await _count(db, "SELECT count(*) FROM dur_ingredient_contraindications WHERE remark LIKE 'derived%'")
    print(f"  {'품목쌍에서 합성된 규칙:':<26}{derived:>8,}건  (remark='derived-from-product')")


async def _drug_anomalies(db) -> None:
    print(f"\n{SEP}\n3. drugs 테이블 이상 데이터\n{SEP}")
    for label, sql, warning in WARN_IF_NONZERO:
        count = await _count(db, sql)
        print(f"  {label + ':':<26}{count:>8,}건  {('⚠️ ' + warning).strip() if count else '✅'}")


async def _known_pairs(db, problems: list[str]) -> None:
    print(f"\n{SEP}\n4. 알려진 병용금기 쌍 — 성분 경로로 탐지되나 (샘플)\n{SEP}")
    for a, b in KNOWN_PAIRS:
        hit = (await db.execute(text(KNOWN_PAIR_SQL), {"a": f"%{a}%", "b": f"%{b}%"})).fetchone()
        if hit:
            print(f"  {a} + {b}: ✅ {(hit.prohibit_content or hit.remark or '')[:44]}")
        else:
            print(f"  {a} + {b}: ❌ 규칙 없음")
            problems.append(f"알려진 병용금기 {a} + {b} 탐지 안 됨")


async def validate() -> list[str]:
    problems: list[str] = []
    async with AsyncSessionLocal() as db:
        await _overview(db, problems)
        await _rule_anomalies(db, problems)
        await _drug_anomalies(db)
        await _known_pairs(db, problems)
    return problems


problems = asyncio.run(validate())
print(f"\n{SEP}")
if problems:
    print("품질 게이트 실패:")
    for p in problems:
        print(f"  ❌ {p}")
    sys.exit(1)
print("품질 게이트 통과")
