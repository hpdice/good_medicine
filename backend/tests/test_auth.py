import time

from app.config import settings
from app.core.login_guard import LoginFailureGuard


def _register_payload(email: str = "test@example.com") -> dict:
    return {
        "email": email,
        "password": "testpass123",
        "name": "테스트유저",
        "privacy_consent": True,
        "health_data_consent": True,
    }


async def test_register_success(client):
    res = await client.post("/auth/register", json=_register_payload())
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "test@example.com"
    assert body["name"] == "테스트유저"
    assert "id" in body


async def test_register_duplicate_email_rejected(client):
    payload = _register_payload()
    res1 = await client.post("/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/auth/register", json=payload)
    assert res2.status_code == 409


async def test_register_without_consent_rejected(client):
    payload = _register_payload()
    payload["privacy_consent"] = False
    res = await client.post("/auth/register", json=payload)
    assert res.status_code == 422


async def test_login_success_returns_tokens(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)

    res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_rejected(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)

    res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": "wrong-password"}
    )
    assert res.status_code == 401


async def test_protected_endpoint_requires_token(client):
    res = await client.get("/users/me")
    assert res.status_code in (401, 403)


async def test_refresh_token_is_single_use(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)
    login_res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    refresh_token = login_res.json()["refresh_token"]

    first = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200

    # 같은 refresh token을 두 번째로 쓰면 이미 폐기되어 실패해야 한다
    second = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401


async def test_password_over_72_bytes_rejected(client):
    # bcrypt는 UTF-8 72바이트를 넘는 비밀번호를 자동 잘라내므로, 스키마
    # 단계에서 명확히 거부해야 한다 (한글 음절당 3바이트 — 30자 = 90바이트).
    payload = _register_payload()
    payload["password"] = "가나다라마바사아자차카타파하가나다라마바사아자차카타파하가나"
    res = await client.post("/auth/register", json=payload)
    assert res.status_code == 422


async def test_delete_then_reregister_with_same_email(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)
    login_res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    access_token = login_res.json()["access_token"]

    delete_res = await client.delete(
        "/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert delete_res.status_code == 204

    # 탈퇴 시 email이 tombstone 처리되어 같은 이메일로 재가입이 가능해야 한다
    reregister_res = await client.post("/auth/register", json=payload)
    assert reregister_res.status_code == 201

    # 탈퇴한 계정은 비활성화되어 원래 비밀번호로 로그인할 수 없어야 한다 (재가입한
    # 새 계정과는 별개 레코드)
    relogin_res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert relogin_res.status_code == 200


async def _login(client, email: str, password: str):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_login_locked_after_repeated_failures_even_with_correct_password(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)

    for _ in range(settings.LOGIN_FAILURE_LIMIT):
        res = await _login(client, payload["email"], "wrong-password")
        assert res.status_code == 401

    # 잠긴 뒤에는 맞는 비밀번호도 거부 — 안 그러면 공격자가 계속 시도할 수 있다
    res = await _login(client, payload["email"], payload["password"])
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0


async def test_login_lock_is_per_account(client):
    a, b = _register_payload("a@example.com"), _register_payload("b@example.com")
    await client.post("/auth/register", json=a)
    await client.post("/auth/register", json=b)

    for _ in range(settings.LOGIN_FAILURE_LIMIT):
        await _login(client, a["email"], "wrong-password")

    assert (await _login(client, a["email"], a["password"])).status_code == 429
    assert (await _login(client, b["email"], b["password"])).status_code == 200


async def test_successful_login_resets_failure_count(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)

    for _ in range(settings.LOGIN_FAILURE_LIMIT - 1):
        await _login(client, payload["email"], "wrong-password")
    assert (await _login(client, payload["email"], payload["password"])).status_code == 200

    # 성공으로 카운터가 비워졌으므로 다시 LIMIT-1번 틀려도 잠기지 않는다
    for _ in range(settings.LOGIN_FAILURE_LIMIT - 1):
        await _login(client, payload["email"], "wrong-password")
    assert (await _login(client, payload["email"], payload["password"])).status_code == 200


async def test_unknown_email_failures_are_counted_too(client):
    # 존재하지 않는 이메일도 같은 응답(401→429)이어야 가입 여부가 새지 않는다
    for _ in range(settings.LOGIN_FAILURE_LIMIT):
        assert (await _login(client, "ghost@example.com", "whatever123")).status_code == 401
    assert (await _login(client, "ghost@example.com", "whatever123")).status_code == 429


def test_login_guard_window_expires():
    guard = LoginFailureGuard(limit=2, window_seconds=0.05)
    guard.record_failure("x@example.com")
    guard.record_failure("X@Example.com ")  # 대소문자·공백은 같은 계정
    assert guard.retry_after("x@example.com") > 0
    time.sleep(0.07)
    assert guard.retry_after("x@example.com") == 0
