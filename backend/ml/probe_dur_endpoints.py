"""DUR 관련 공공데이터 API의 추가 오퍼레이션 존재 여부를 실제로 호출해 확인한다.

14회차에서 이미 getUsjntCautionInfoList03 등 몇 개 이름을 시도해 404를 확인했으나,
'효능군중복주의' 관련 실제 오퍼레이션 이름은 확인하지 못했다. data.go.kr의
DUR 품목정보 서비스 설명에 '효능군중복주의'가 명시되어 있으므로, 그럴듯한
이름 후보들을 폭넓게 직접 시도해본다.
"""
import asyncio
import httpx
from app.config import settings

CANDIDATES = [
    "getSpcifyAgrdeTabooInfoList03",   # 특정연령대금기
    "getPwomTabooInfoList03",           # 임부금기
    "getCpctyAtentInfoList03",          # 용량주의
    "getMdctnPdAtentInfoList03",        # 투여기간주의
    "getOdsnAtentInfoList03",           # 노인주의
    "getEfcyDplctInfoList03",           # 효능군중복주의 (추정1)
    "getEfcyGrpDplctInfoList03",        # 효능군중복주의 (추정2)
    "getSeobangjungInfoList03",         # 서방정분할주의
    "getDivunitAtentInfoList03",        # 서방정분할주의 (추정2)
    "getDurPrdlstInfoList03",           # DUR 품목정보
]


async def probe(client: httpx.AsyncClient, base_url: str, op: str):
    url = f"{base_url}/{op}"
    params = {"serviceKey": settings.PUBLIC_DATA_API_KEY, "pageNo": 1, "numOfRows": 1, "type": "json"}
    try:
        resp = await client.get(url, params=params, timeout=15)
        status = resp.status_code
        body_preview = resp.text[:200].replace("\n", " ")
        print(f"[{status}] {op}\n    {body_preview}\n")
    except Exception as e:
        print(f"[ERROR] {op}: {e}\n")


async def main():
    async with httpx.AsyncClient() as client:
        for op in CANDIDATES:
            await probe(client, settings.DUR_PRODUCT_API_URL, op)


asyncio.run(main())
