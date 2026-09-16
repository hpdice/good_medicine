"""PublicDataService — 여러 동기화 책임을 믹스인으로 조합한다.

`sync.py`가 `PublicDataService(db, progress_cb=...)`를 만들어 메서드 이름으로
직접 호출하므로(`run_sync()`), 클래스 자체는 하나로 유지하고 책임별로 파일만
나눴다. 이렇게 하면 `sync.py`/`drug_service.py`의 기존 import는 그대로 통과한다."""
from .base import _SyncBase
from .drug_approval_sync import DrugApprovalSyncMixin
from .drug_identification_sync import DrugIdentificationSyncMixin
from .drug_overview_sync import DrugOverviewSyncMixin
from .dur_sync import DurSyncMixin
from .maintenance import MaintenanceMixin
from .risk_tags import RiskTagsMixin


class PublicDataService(
    _SyncBase,
    DrugOverviewSyncMixin,
    DrugApprovalSyncMixin,
    DrugIdentificationSyncMixin,
    DurSyncMixin,
    MaintenanceMixin,
    RiskTagsMixin,
):
    pass
