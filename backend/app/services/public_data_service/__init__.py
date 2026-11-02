"""
공공데이터포털 의약품 API 통합 서비스.
- 의약품개요정보(e약은요): DrbEasyDrugInfoService
- 의약품안전사용서비스(DUR) 품목정보: DURPrdlstInfoService03  (응답에 성분코드 INGR_CODE 포함)
- 의약품안전사용서비스(DUR) 성분정보: DURIrdntInfoService03  (성분 단위 규칙 + 성분코드·한글·영문 성분명)
- 의약품 제품 허가정보: DrugPrdtPrmsnInfoService07
- 심평원 약가마스터(파일데이터 CSV): 품목기준코드 → 일반명코드 → 영문 일반명

이 패키지는 책임별 모듈로 나뉘어 있고, 이 `__init__.py`가
하위 모듈 이동과 무관하게 기존 import 경로(`from app.services.public_data_service import
PublicDataService`/`_make_drug_key`)를 그대로 유지한다.
"""
from .helpers import _make_drug_key
from .service import PublicDataService

__all__ = ["PublicDataService", "_make_drug_key"]
