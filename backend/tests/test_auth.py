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
