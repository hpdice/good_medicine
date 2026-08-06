import asyncio

import httpx

from app.config import settings
from app.core.logging import logger


class OllamaUnavailableError(Exception):
    """Ollama 서버가 응답하지 않거나 시간 초과됐을 때. 가이드 생성만 실패시키고
    quick-check 등 규칙 기반 판정에는 영향이 없어야 하므로 별도 예외로 구분한다."""


class OllamaClient:
    """로컬 Ollama 서버(`/api/generate`) 호출 — 위험도 판정에는 관여하지 않고,
    이미 확정된 판정 결과를 사람이 읽을 설명으로 풀어쓰는 용도로만 쓴다."""

    def __init__(self) -> None:
        self._base_url = settings.OLLAMA_BASE_URL
        self._model = settings.OLLAMA_MODEL
        self._timeout = settings.OLLAMA_TIMEOUT_SECONDS

    async def generate(self, prompt: str, system: str | None = None) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            # 실측 결과 모델을 새로 GPU에 올리는 데 87초~2분 30초가 걸림(9GB, 첫 요청
            # 또는 기본 5분 유휴 후 언로드 시). 요청 사이 간격이 있어도 계속 로드된
            # 상태를 유지해 매번 이 콜드스타트 비용이 재발하지 않게 한다.
            "keep_alive": "30m",
        }
        if system:
            payload["system"] = system
        return await self._request(payload)

    async def keep_warm(self) -> None:
        """모델을 GPU에 로드된 상태로 유지하는 용도의 최소 호출.

        실제 응답 내용은 필요 없으므로 `num_predict`를 1로 줄여 워밍업 자체의
        연산 비용을 최소화한다. 백그라운드 주기 태스크에서 호출하는 용도라
        실패해도 예외를 던지지 않고 조용히 로그만 남긴다 — 실제 요청이 들어왔을
        때 재시도/폴백은 generate()가 책임진다.
        """
        payload = {
            "model": self._model,
            "prompt": "ping",
            "stream": False,
            "keep_alive": "30m",
            "options": {"num_predict": 1},
        }
        try:
            await self._request(payload)
        except OllamaUnavailableError as e:
            logger.warning(f"Ollama 워밍업 실패 (다음 주기에 재시도): {e}")

    async def _request(self, payload: dict) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            for attempt in range(2):
                try:
                    resp = await client.post("/api/generate", json=payload)
                    resp.raise_for_status()
                    return resp.json()["response"].strip()
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    if attempt == 0:
                        logger.warning(f"Ollama 연결 실패, 재시도: {e}")
                        await asyncio.sleep(1)
                        continue
                    logger.error(f"Ollama 연결 실패 (재시도 후에도): {e}")
                    raise OllamaUnavailableError("로컬 LLM 서버에 연결할 수 없습니다.") from e
                except httpx.TimeoutException as e:
                    logger.error(f"Ollama 응답 시간 초과: {e}")
                    raise OllamaUnavailableError("로컬 LLM 응답이 시간 초과됐습니다.") from e
                except httpx.HTTPStatusError as e:
                    logger.error(f"Ollama 오류 응답: {e.response.status_code} {e.response.text}")
                    raise OllamaUnavailableError("로컬 LLM 서버 오류가 발생했습니다.") from e

        raise OllamaUnavailableError("로컬 LLM 서버에 연결할 수 없습니다.")
