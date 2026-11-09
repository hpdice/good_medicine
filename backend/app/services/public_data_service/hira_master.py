"""심평원 약가마스터 CSV(공공데이터포털 파일데이터) 적재 — API가 아니라 내려받은 파일을 읽는다.

파일은 `SYNC_STATE_DIR/hira/`에 둔다(compose의 sync_state 볼륨):
  docker cp <의약품표준코드.csv> drugtest-backend-1:/var/lib/goodmedicine/hira/
  docker cp <의약품주성분.csv>   drugtest-backend-1:/var/lib/goodmedicine/hira/
이름에 '의약품표준코드'·'의약품주성분'이 들어간 파일 중 가장 최근 수정본을 쓴다(인코딩 CP949).
지난번과 같은 파일(SHA-256)이면 통째로 건너뛰고, 새 파일이면 값이 바뀐 행만 쓴다."""
import csv
import glob
import hashlib
import io
import json
import os

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.core.logging import logger
from app.models.hira import HiraGenCode, HiraGenIngredient, HiraItemGenCode

from .base import _SyncBase
from .helpers import (
    hira_gen_codes_from_rows,
    hira_gen_ingredients_from_rows,
    hira_item_gen_codes_from_rows,
)

_BATCH = 1000


def _hira_dir() -> str:
    return os.path.join(settings.SYNC_STATE_DIR, "hira")


def _state_path() -> str:
    return os.path.join(_hira_dir(), "loaded.json")


class HiraMasterMixin(_SyncBase):
    # 종류 -> (파일 이름에 들어간 말, [(행 변환 함수, 모델, 유일 키 열, 유일 제약 이름), ...]) — 단계는 앞에서부터 적재한다
    # (주성분 파일은 일반명코드 속성을 먼저 넣어야 성분 행의 외래 키가 맞는다)
    HIRA_FILES = {
        "표준코드": ("의약품표준코드", [
            (hira_item_gen_codes_from_rows, HiraItemGenCode, ("item_seq", "gen_code"), "uq_hira_item_gen_code"),
        ]),
        "주성분": ("의약품주성분", [
            (hira_gen_codes_from_rows, HiraGenCode, ("gen_code",), "hira_gen_codes_pkey"),
            (hira_gen_ingredients_from_rows, HiraGenIngredient, ("gen_code", "seq"), "uq_hira_gen_ingredient_seq"),
        ]),
    }

    async def load_hira_master(self) -> int:
        """두 파일을 적재하고 추가·갱신한 행 수를 돌려준다. 파일이 없으면 RuntimeError."""
        try:
            with open(_state_path(), encoding="utf-8") as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}

        written = 0
        for kind, (pattern, steps) in self.HIRA_FILES.items():
            paths = sorted(glob.glob(os.path.join(_hira_dir(), f"*{pattern}*.csv")), key=os.path.getmtime)
            if not paths:
                raise RuntimeError(f"심평원 {kind} 파일 없음: {_hira_dir()}/*{pattern}*.csv")
            path = paths[-1]
            raw = open(path, "rb").read()
            digest = hashlib.sha256(raw).hexdigest()
            if state.get(kind, {}).get("sha256") == digest:
                logger.warning("심평원 %s: 지난번과 같은 파일이라 건너뜀 (%s)", kind, os.path.basename(path))
                continue

            csv_rows = list(csv.DictReader(io.StringIO(raw.decode("cp949"))))
            n = 0
            for to_rows, model, key_cols, constraint in steps:
                values = to_rows(csv_rows)
                n += await self._upsert_changed(model, key_cols, constraint, values)
                if model is HiraGenIngredient:
                    n += await self._drop_stale_ingredient_rows(set(values))
            await self.db.commit()
            written += n
            state[kind] = {"file": os.path.basename(path), "sha256": digest, "rows": len(values)}
            logger.warning("심평원 %s: %s → %d행 중 %d행 추가·갱신·삭제", kind, os.path.basename(path), len(values), n)

        os.makedirs(_hira_dir(), exist_ok=True)
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return written

    async def _upsert_changed(self, model, key_cols: tuple[str, ...], constraint: str, values: dict) -> int:
        """없는 행은 넣고, 있는 행은 값이 달라졌을 때만 갱신한다(같으면 건너뜀). 쓴 행 수."""
        rows = [dict(zip(key_cols, key)) | v for key, v in values.items()]
        written = 0
        for i in range(0, len(rows), _BATCH):
            stmt = pg_insert(model).values(rows[i:i + _BATCH])
            cols = [c for c in rows[0] if c not in key_cols]
            result = await self.db.execute(stmt.on_conflict_do_update(
                constraint=constraint,
                set_={c: stmt.excluded[c] for c in cols},
                where=or_(*(getattr(model, c).is_distinct_from(stmt.excluded[c]) for c in cols)),
            ))
            written += result.rowcount  # type: ignore[attr-defined]
        return written

    async def _drop_stale_ingredient_rows(self, keys: set[tuple[str, int]]) -> int:
        """새 파일에서 성분 수가 줄어든 일반명코드의 남는 순번 행을 지운다(파일이 기준인 캐시)."""
        codes = {gen for gen, _ in keys}
        stale = [
            row_id for row_id, gen, seq in (await self.db.execute(
                select(HiraGenIngredient.id, HiraGenIngredient.gen_code, HiraGenIngredient.seq)
            )).all()
            if gen in codes and (gen, seq) not in keys
        ]
        for i in range(0, len(stale), _BATCH):
            await self.db.execute(delete(HiraGenIngredient).where(HiraGenIngredient.id.in_(stale[i:i + _BATCH])))
        return len(stale)
