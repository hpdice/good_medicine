"""prohibit_content → 로컬 LLM 위험/증상 태그 1회 추출 (판정에는 관여하지 않음, 표시용)."""
import json

from sqlalchemy import text

from app.core.logging import logger

from .base import _SyncBase
from .helpers import _parse_tag_array


class RiskTagsMixin(_SyncBase):
    _RISK_TAG_SYSTEM = (
        "너는 의약품 병용금기 설명 문장에서 '환자에게 나타날 수 있는 위험/증상'만 뽑아내는 추출기다. "
        "문장에 없는 내용은 지어내지 마라. 효소 저해 같은 '기전'이 아니라 결과(출혈, 신독성, QT 연장 등)를 뽑아라."
    )

    async def extract_risk_tags(self, batch_commit: int = 20) -> int:
        """`dur_ingredient_contraindications.prohibit_content`(distinct ~127개)를 로컬 LLM으로
        1회 태그화해 `risk_tags` JSONB에 저장한다. `risk_tags`가 NULL인 행만 처리(재실행 안전).
        Ollama가 없으면 조용히 스킵(판정엔 영향 없음).
        """
        from app.services.ollama_client import OllamaClient, OllamaUnavailableError

        contents = (await self.db.execute(text("""
            SELECT DISTINCT prohibit_content FROM dur_ingredient_contraindications
            WHERE prohibit_content IS NOT NULL AND risk_tags IS NULL
        """))).scalars().all()
        if not contents:
            return 0

        ollama = OllamaClient()
        done = 0
        for i, pc in enumerate(contents, 1):
            prompt = (
                f'다음 문장에서 위험/증상을 한국어 명사구로 최대 4개 뽑아 JSON 배열로만 답해라. '
                f'없으면 []. 문장: "{pc}"'
            )
            try:
                raw = await ollama.generate(prompt, system=self._RISK_TAG_SYSTEM)
            except OllamaUnavailableError:
                logger.warning("Ollama 미가용 — risk_tags 추출 중단 (%d/%d 처리됨)", done, len(contents))
                break
            tags = _parse_tag_array(raw)
            await self.db.execute(
                text("UPDATE dur_ingredient_contraindications SET risk_tags = :t "
                     "WHERE prohibit_content = :pc"),
                {"t": json.dumps(tags, ensure_ascii=False), "pc": pc},
            )
            done += 1
            if i % batch_commit == 0:
                await self.db.commit()
        await self.db.commit()
        logger.info(f"risk_tags 추출 완료: {done}/{len(contents)} distinct 문장")
        return done
