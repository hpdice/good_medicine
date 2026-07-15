import asyncio
import json
import httpx
from app.config import settings

OPS = ["getEfcyDplctInfoList03", "getSpcifyAgrdeTabooInfoList03", "getOdsnAtentInfoList03"]


async def main():
    async with httpx.AsyncClient() as client:
        for op in OPS:
            url = f"{settings.DUR_PRODUCT_API_URL}/{op}"
            params = {"serviceKey": settings.PUBLIC_DATA_API_KEY, "pageNo": 1, "numOfRows": 2, "type": "json"}
            resp = await client.get(url, params=params, timeout=15)
            data = resp.json()
            items = data.get("body", {}).get("items", [])
            print(f"===== {op} (totalCount={data.get('body', {}).get('totalCount')}) =====")
            print(json.dumps(items, ensure_ascii=False, indent=2))
            print()


asyncio.run(main())
