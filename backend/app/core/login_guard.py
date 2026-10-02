"""계정(이메일)별 로그인 **실패** 횟수 제한.

IP 단위 Rate Limit(`LOGIN_RATE_LIMIT`)은 성공한 로그인도 세고, 같은 공유기·행사장 와이파이 뒤의
여러 사용자를 한 묶음으로 센다. 비밀번호 무차별 대입을 막는 데는 "이 계정에 대한 실패 횟수"가
정확한 기준이라, 실패만 이메일 단위로 따로 센다. 성공하면 그 계정의 카운터는 비워진다.

- 잠긴 동안에는 **맞는 비밀번호도 거부**한다(그렇지 않으면 공격자가 계속 시도할 수 있다).
- 존재하지 않는 이메일도 똑같이 센다 — 응답이 달라지면 가입 여부를 알아낼 수 있다.
- 프로세스 메모리에만 저장한다(slowapi 기본 스토리지와 같은 수준). 재시작하면 초기화되고, uvicorn
  워커를 여러 개로 늘리면 워커별로 센다 — 지금은 단일 프로세스 배포다.
- 한계: 남의 이메일로 일부러 실패를 쌓아 그 사람을 잠시(기본 15분) 잠글 수 있다. 계정 단위 잠금의
  일반적인 트레이드오프이고, 영구 잠금이 아니라 창이 지나면 풀린다.
"""

import time
from collections import deque

from app.config import settings

_MAX_TRACKED = 10_000  # 서로 다른 이메일을 무한히 시도해 메모리를 채우는 것을 막는다


class LoginFailureGuard:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._failures: dict[str, deque[float]] = {}

    @staticmethod
    def _key(email: str) -> str:
        return email.strip().lower()

    def _recent(self, key: str, now: float) -> deque[float]:
        times = self._failures.get(key)
        if times is None:
            return deque()
        while times and now - times[0] >= self._window:
            times.popleft()
        if not times:
            del self._failures[key]
        return times

    def retry_after(self, email: str) -> int:
        """잠겨 있으면 풀리기까지 남은 초(올림), 아니면 0."""
        now = time.monotonic()
        times = self._recent(self._key(email), now)
        if len(times) < self._limit:
            return 0
        return max(1, int(self._window - (now - times[0])) + 1)

    def record_failure(self, email: str) -> None:
        now = time.monotonic()
        if len(self._failures) >= _MAX_TRACKED:
            for k in list(self._failures):
                self._recent(k, now)
            if len(self._failures) >= _MAX_TRACKED:
                self._failures.pop(next(iter(self._failures)))
        key = self._key(email)
        self._failures.setdefault(key, deque()).append(now)
        self._recent(key, now)

    def reset(self, email: str) -> None:
        self._failures.pop(self._key(email), None)

    def clear(self) -> None:
        self._failures.clear()


login_guard = LoginFailureGuard(
    settings.LOGIN_FAILURE_LIMIT, settings.LOGIN_FAILURE_WINDOW_SECONDS
)
