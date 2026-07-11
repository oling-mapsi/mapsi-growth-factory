import hashlib
import hmac
import json


def build_signature(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, signature


def github_headers(delivery_id: str, signature: str) -> dict[str, str]:
    return {
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": signature,
    }


def base_payload() -> dict:
    return {
        "repository": {"full_name": "mapsi/mapsi-v6", "default_branch": "main"},
        "installation": {"id": 12345},
        "after": "abc123",
        "commits": [],
        "mock_change_notes": [],
    }


def test_github_webhook_rejects_invalid_signature(client) -> None:
    payload = base_payload()
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        headers=github_headers("delivery-1", "sha256=invalid"),
        content=body,
    )
    assert response.status_code == 401


def test_github_webhook_is_idempotent_on_duplicate_delivery(client) -> None:
    payload = base_payload()
    payload["mock_change_notes"] = [
        {
            "sha": "abc123",
            "change_note_path": "growth/change-notes/change-1.yaml",
            "capability_key": "cap-1",
            "summary": "Delivered and deployable feature",
            "eligible_for_communication": True,
            "confidential": False,
            "target_client_key": "",
            "contract_version": "1.0.0",
            "deployment_ref": "deploy-1",
            "production_status": "success",
            "deployment_proven": True,
        }
    ]
    body, signature = build_signature("test-github-secret", payload)
    first = client.post("/webhooks/github", headers=github_headers("delivery-2", signature), content=body)
    second = client.post("/webhooks/github", headers=github_headers("delivery-2", signature), content=body)
    assert first.status_code == 202
    assert first.json()["status"] == "processed"
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"


def test_github_webhook_rejects_unauthorized_repository(client) -> None:
    payload = base_payload()
    payload["repository"]["full_name"] = "other/repo"
    body, signature = build_signature("test-github-secret", payload)
    response = client.post("/webhooks/github", headers=github_headers("delivery-3", signature), content=body)
    assert response.status_code == 403


def test_github_webhook_skips_confidential_change_note(client) -> None:
    payload = base_payload()
    payload["mock_change_notes"] = [
        {
            "sha": "abc124",
            "change_note_path": "growth/change-notes/change-2.yaml",
            "capability_key": "cap-2",
            "summary": "Confidential feature",
            "eligible_for_communication": True,
            "confidential": True,
            "target_client_key": "",
            "contract_version": "1.0.0",
            "deployment_ref": "deploy-2",
            "production_status": "success",
            "deployment_proven": True,
        }
    ]
    body, signature = build_signature("test-github-secret", payload)
    response = client.post("/webhooks/github", headers=github_headers("delivery-4", signature), content=body)
    assert response.status_code == 202
    assert response.json()["product_changes_created"] == 0


def test_github_webhook_skips_undeployed_change(client) -> None:
    payload = base_payload()
    payload["mock_change_notes"] = [
        {
            "sha": "abc125",
            "change_note_path": "growth/change-notes/change-3.yaml",
            "capability_key": "cap-3",
            "summary": "Undeployed feature",
            "eligible_for_communication": True,
            "confidential": False,
            "target_client_key": "",
            "contract_version": "1.0.0",
            "deployment_ref": "",
            "production_status": "pending",
            "deployment_proven": False,
        }
    ]
    body, signature = build_signature("test-github-secret", payload)
    response = client.post("/webhooks/github", headers=github_headers("delivery-5", signature), content=body)
    assert response.status_code == 202
    assert response.json()["product_changes_created"] == 0


def test_github_webhook_rejects_schema_break(client) -> None:
    payload = base_payload()
    payload["mock_change_notes"] = [
        {
            "sha": "abc126",
            "change_note_path": "growth/change-notes/change-4.yaml",
            "capability_key": "cap-4",
            "summary": "Schema break",
            "eligible_for_communication": True,
            "confidential": False,
            "target_client_key": "",
            "contract_version": "2.0.0",
            "deployment_ref": "deploy-4",
            "production_status": "success",
            "deployment_proven": True,
        }
    ]
    body, signature = build_signature("test-github-secret", payload)
    response = client.post("/webhooks/github", headers=github_headers("delivery-6", signature), content=body)
    assert response.status_code == 422
