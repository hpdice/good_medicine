"""병용금기 푸시는 Google FCM(해외)을 거치므로 약 이름·ID를 싣지 않는다."""
from app.services import fcm_service
from tests.factories import make_contraindication, make_drug, register_and_login


async def test_contraindication_push_carries_no_drug_identity(client, session_factory, monkeypatch):
    sent = []

    async def fake_send_push(token, title, body, data=None):
        sent.append({"title": title, "body": body, "data": data or {}})
        return True

    monkeypatch.setattr(fcm_service, "is_configured", lambda: True)
    monkeypatch.setattr(fcm_service, "send_push", fake_send_push)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트푸시심바스타틴정")
        drug_b = await make_drug(session, "테스트푸시클래리스정")
        await make_contraindication(session, drug_a, drug_b, mechanism="근병증 위험증가")

    headers = {"Authorization": f"Bearer {await register_and_login(client)}"}
    assert (await client.patch("/users/me", json={"fcm_token": "test-device-token"}, headers=headers)).status_code == 200
    for drug in (drug_a, drug_b):
        assert (await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)).status_code == 201

    assert len(sent) == 1  # 두 번째 약을 넣는 순간 한 번 알린다
    payload = " ".join([sent[0]["title"], sent[0]["body"], *sent[0]["data"].keys(), *sent[0]["data"].values()])
    for leaked in (drug_a.item_name, drug_b.item_name, str(drug_a.id), str(drug_b.id), "근병증"):
        assert leaked not in payload
    assert sent[0]["data"] == {"type": "contraindication"}
