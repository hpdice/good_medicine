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
