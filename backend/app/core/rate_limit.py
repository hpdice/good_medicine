"""공용 Rate Limiter 인스턴스와 키 함수.

이전엔 main.py·auth.py·analysis.py·drugs.py가 각자
`Limiter(key_func=get_remote_address)`를 만들어 4개가 따로 존재했다(스토리지도 별개).
하나로 모아 `app.state.limiter`와 라우터 데코레이터가 같은 인스턴스를 쓰게 한다.

키 함수가 `get_remote_address`(= 직접 연결한 상대의 IP)였을 때, 배포 환경에서는 모든
요청이 Tailscale Funnel 컨테이너를 거쳐 들어와 **전 사용자가 IP 하나를 공유**했다 —
로그인 5회/15분이 서비스 전체 한도가 되는 문제(2026-09-30 실측). 그래서:

- 실제 클라이언트 IP는 `client_ip()`로 구한다. `X-Forwarded-For`는 **신뢰 프록시에서 온
  요청일 때만** 믿는다(누구나 헤더를 위조할 수 있으므로). Tailscale serve/Funnel은 이 헤더를
  `Set()`으로 덮어써 실제 출발지 주소를 넣는다(tailscale ipn/ipnlocal/serve.go
  `addProxyForwardedHeaders`).
- 로그인한 사용자의 요청은 IP가 아니라 사용자 ID로 센다(`user_or_ip_key`) — 같은 공유기·
  캠퍼스 와이파이 뒤의 여러 사용자가 서로의 한도를 깎지 않게.
"""

import ipaddress

from jose import JWTError
from slowapi import Limiter
from starlette.requests import Request

from app.config import settings
from app.core.security import decode_token

_TRUSTED_PROXY_NETWORKS = [ipaddress.ip_network(c) for c in settings.TRUSTED_PROXY_CIDRS]


def _is_trusted_proxy(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)


def client_ip(request: Request) -> str:
    """실제 클라이언트 IP. 신뢰 프록시를 거친 요청이면 `X-Forwarded-For`의 가장 오른쪽 값
    (= 신뢰 프록시가 직접 본 출발지)을, 아니면 직접 연결한 상대의 주소를 쓴다."""
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if peer and forwarded and _is_trusted_proxy(peer):
        candidate = forwarded.split(",")[-1].strip()
        if candidate:
            return candidate
    return peer or "unknown"


def user_or_ip_key(request: Request) -> str:
    """유효한 Access Token이 있으면 사용자 단위, 없으면 IP 단위로 센다."""
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = decode_token(token)
            if payload.get("type") == "access" and payload.get("sub"):
                return f"user:{payload['sub']}"
        except JWTError:
            pass
    return f"ip:{client_ip(request)}"


limiter = Limiter(key_func=client_ip)
