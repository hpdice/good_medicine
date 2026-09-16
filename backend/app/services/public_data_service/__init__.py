"""
공공데이터포털 의약품 API 통합 서비스.
- 의약품개요정보(e약은요): DrbEasyDrugInfoService
- 의약품안전사용서비스(DUR) 품목정보: DURPrdlstInfoService03  (응답에 성분코드 INGR_CODE 포함)
- 의약품 제품 허가정보: DrugPrdtPrmsnInfoService07
(구 DUR 성분정보 API `DURIrdntInfoService`는 폐기됨 — 성분코드는 DUR 품목정보 응답에서 캡처)
(낱알식별 API `MdcinGrnIdntfcInfoService01`은 2026-09-17 제거됨 — 사진 기반 알약 인식 기능
자체가 2026-09-12 폐기 확정된 뒤에도 프론트에서 전혀 안 쓰는 컬럼·동기화 코드가 남아있었음)

2026-09-12: 파일 하나(1,114줄)였던 걸 책임별로 나눠 패키지화했다 — 이 `__init__.py`가
하위 모듈 이동과 무관하게 기존 import 경로(`from app.services.public_data_service import
PublicDataService`/`_make_drug_key`)를 그대로 유지한다.
"""
from .helpers import _make_drug_key
from .service import PublicDataService

__all__ = ["PublicDataService", "_make_drug_key"]
