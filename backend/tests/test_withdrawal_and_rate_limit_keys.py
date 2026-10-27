"""운영 결함 회귀 테스트.

1. 탈퇴하면 복약 데이터가 지워지고, 탈퇴 전에 받은 Access/Refresh Token은 더 이상 통하지 않는다
2. Rate Limit 키가 직접 연결 상대의 IP(= 배포 시 Tailscale 프록시)면 전 사용자가 한도를
   공유하므로 — 키 함수 단위로 검증한다(테스트 환경은 로그인 한도를 풀어 둠).
"""
from sqlalchemy import func, select
from starlette.requests import Request

from app.core.rate_limit import client_ip, user_or_ip_key
from app.core.security import create_access_token, create_refresh_token
from app.models.medicine_box import MedicineBoxEntry
from app.models.user import AuditLog
from tests.factories import make_drug


def _payload(email: str) -> dict:
    return {
        "email": email, "password": "password123", "name": "탈퇴테스트",
        "privacy_consent": True, "health_data_consent": True,
    }


async def _register_login(client, email: str) -> dict:
    await client.post("/auth/register", json=_payload(email))
    res = await client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()


# ---------- 탈퇴 ----------

async def test_withdrawal_deletes_medication_data(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "탈퇴데이터정")
    tokens = await _register_login(client, "withdraw-data@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    added = await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)
    assert added.status_code == 201

    assert (await client.delete("/users/me", headers=headers)).status_code == 204

    async with session_factory() as session:
        left = await session.scalar(select(func.count()).select_from(MedicineBoxEntry))
        logged = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "delete_account")
        )
    assert left == 0
    assert logged == 1


async def test_old_access_token_rejected_after_withdrawal(client):
    tokens = await _register_login(client, "withdraw-access@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.delete("/users/me", headers=headers)).status_code == 204

    res = await client.get("/medicine-box", headers=headers)
    assert res.status_code == 401


async def test_old_refresh_token_rejected_after_withdrawal(client):
    tokens = await _register_login(client, "withdraw-refresh@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.delete("/users/me", headers=headers)).status_code == 204

    res = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 401


# ---------- Rate Limit 키 ----------

def _request(peer: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": raw, "client": (peer, 12345),
    })


def test_client_ip_uses_forwarded_header_from_trusted_proxy():
    # Tailscale 컨테이너(compose 내부망)가 실제 출발지를 X-Forwarded-For 로 넘긴 경우
    req = _request("172.18.0.5", {"X-Forwarded-For": "203.0.113.7"})
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_takes_rightmost_forwarded_value():
    # 앞쪽 값은 클라이언트가 위조했을 수 있다 — 신뢰 프록시가 붙인 가장 오른쪽만 믿는다
    req = _request("172.18.0.5", {"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_ignores_forwarded_header_from_untrusted_peer():
    # 신뢰 프록시가 아닌 상대가 보낸 헤더는 위조일 수 있으므로 무시
    req = _request("198.51.100.9", {"X-Forwarded-For": "203.0.113.7"})
    assert client_ip(req) == "198.51.100.9"


def test_different_clients_behind_proxy_get_different_keys():
    a = _request("172.18.0.5", {"X-Forwarded-For": "203.0.113.1"})
    b = _request("172.18.0.5", {"X-Forwarded-For": "203.0.113.2"})
    assert client_ip(a) != client_ip(b)


def test_user_or_ip_key_counts_logged_in_users_separately():
    access = create_access_token("11111111-1111-1111-1111-111111111111")
    req = _request(
        "172.18.0.5", {"Authorization": f"Bearer {access}", "X-Forwarded-For": "203.0.113.1"}
    )
    assert user_or_ip_key(req) == "user:11111111-1111-1111-1111-111111111111"


def test_user_or_ip_key_falls_back_to_ip_for_invalid_or_refresh_token():
    refresh = create_refresh_token("11111111-1111-1111-1111-111111111111")
    for token in ("garbage", refresh):
        req = _request(
            "172.18.0.5", {"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.1"}
        )
        assert user_or_ip_key(req) == "ip:203.0.113.1"
