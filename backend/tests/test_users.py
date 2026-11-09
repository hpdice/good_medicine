from sqlalchemy import select

from app.models.user import User

from .test_auth import _register_payload


async def _login(client, payload):
    res = await client.post(
        "/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    return res.json()["access_token"]


async def test_update_and_get_health_info_roundtrip(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)
    token = await _login(client, payload)
    headers = {"Authorization": f"Bearer {token}"}

    patch_res = await client.patch(
        "/users/me",
        headers=headers,
        json={"health_conditions": ["고혈압"], "allergy_info": ["페니실린"]},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["health_conditions"] == ["고혈압"]
    assert patch_res.json()["allergy_info"] == ["페니실린"]

    get_res = await client.get("/users/me", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["health_conditions"] == ["고혈압"]


async def test_corrupted_encrypted_field_does_not_500(client, session_factory):
    # 암호화 키 로테이션이나 데이터 손상으로 필드 하나가 깨져도 계정 전체가
    # 500이 되지 않고, 해당 필드만 null로 격리되어야 한다.
    payload = _register_payload()
    await client.post("/auth/register", json=payload)
    token = await _login(client, payload)
    headers = {"Authorization": f"Bearer {token}"}

    await client.patch(
        "/users/me", headers=headers, json={"health_conditions": ["당뇨"]}
    )

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == payload["email"]))
        ).scalar_one()
        user.health_conditions_encrypted = "not-valid-base64-ciphertext"
        await session.commit()

    get_res = await client.get("/users/me", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["health_conditions"] is None


async def test_birth_year_can_be_cleared_with_explicit_null_but_not_by_omitting_it(client):
    payload = _register_payload()
    await client.post("/auth/register", json=payload)
    token = await _login(client, payload)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.patch("/users/me", headers=headers, json={"birth_year": 1950})
    assert res.json()["birth_year"] == 1950
    res = await client.patch("/users/me", headers=headers, json={"allergy_info": ["페니실린"]})  # 키 없음 — 그대로
    assert res.json()["birth_year"] == 1950
    res = await client.patch("/users/me", headers=headers, json={"birth_year": None})  # 명시적 null — 지운다
    assert res.status_code == 200 and res.json()["birth_year"] is None
    assert (await client.get("/users/me", headers=headers)).json()["birth_year"] is None
