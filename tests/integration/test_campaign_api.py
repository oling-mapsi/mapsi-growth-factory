def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def test_campaign_api_lifecycle(client) -> None:
    create_response = client.post(
        "/campaigns",
        headers=auth_headers(),
        json={
            "name": "MAPSI Summer Push",
            "objective": "Create awareness",
            "audience": {"name": "CMO", "description": "B2B marketing leaders"},
        },
    )
    assert create_response.status_code == 201
    campaign_id = create_response.json()["id"]

    generate_response = client.post(f"/campaigns/{campaign_id}/generate", headers=auth_headers())
    assert generate_response.status_code == 200
    assert generate_response.json()["status"] == "GENERATED"
    assert len(generate_response.json()["source_evidences"]) == 5

    blocked_publish = client.post(
        f"/campaigns/{campaign_id}/publish",
        headers=auth_headers(),
        json={"channel": "linkedin"},
    )
    assert blocked_publish.status_code == 409

    approve_response = client.post(
        f"/campaigns/{campaign_id}/approve",
        headers=auth_headers(),
        json={"decided_by": "approver@mapsi.fr", "comment": "Approved"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"

    publish_response = client.post(
        f"/campaigns/{campaign_id}/publish",
        headers=auth_headers(),
        json={"channels": ["linkedin", "oling"]},
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "PUBLISHED"
    assert len(publish_response.json()["publications"]) == 2
    assert publish_response.json()["content_assets"][0]["status"] == "APPROVED"


def test_campaign_api_requires_authentication(client) -> None:
    response = client.get("/campaigns")
    assert response.status_code == 401


def test_campaign_api_idempotency_replays_same_response(client) -> None:
    headers = {**auth_headers(), "Idempotency-Key": "create-1"}
    payload = {
        "name": "MAPSI Summer Push",
        "objective": "Create awareness",
        "audience": {"name": "CMO", "description": "B2B marketing leaders"},
    }

    first = client.post("/campaigns", headers=headers, json=payload)
    second = client.post("/campaigns", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_campaign_api_idempotency_rejects_different_payload_same_key(client) -> None:
    headers = {**auth_headers(), "Idempotency-Key": "create-2"}
    first = client.post(
        "/campaigns",
        headers=headers,
        json={
            "name": "Campaign A",
            "objective": "Create awareness",
            "audience": {"name": "CMO", "description": "B2B marketing leaders"},
        },
    )
    second = client.post(
        "/campaigns",
        headers=headers,
        json={
            "name": "Campaign B",
            "objective": "Different objective",
            "audience": {"name": "CTO", "description": "Tech leaders"},
        },
    )

    assert first.status_code == 201
    assert second.status_code == 409
