"""공용 Rate Limiter 인스턴스.

이전엔 main.py·auth.py·analysis.py·drugs.py가 각자
`Limiter(key_func=get_remote_address)`를 만들어 4개가 따로 존재했다(스토리지도 별개).
하나로 모아 `app.state.limiter`와 라우터 데코레이터가 같은 인스턴스를 쓰게 한다.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
