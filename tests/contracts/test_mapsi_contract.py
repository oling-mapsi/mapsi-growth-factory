import json
from pathlib import Path

from fastapi.testclient import TestClient
import jsonschema

from app.generated.mapsi_contract_client import MapsiContractClient
from app.main import create_app
from app.mock_mapsi_server import app as mock_mapsi_app
from scripts.check_mapsi_contract import ensure_no_forbidden_keys, load_json, main as check_main

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts" / "mapsi"


def test_contract_examples_are_valid_and_safe() -> None:
    assert check_main() == 0


def test_product_change_required_fields_present() -> None:
    example = load_json(CONTRACTS / "examples" / "product-change.example.json")
    change = example["items"][0]
    assert {"id", "title", "summary", "url", "published_at", "tags", "communicable"}.issubset(change)


def test_forbidden_data_is_rejected() -> None:
    payload = {"contacts": [{"email": "ok@example.test", "salary": 1000}]}
    try:
        ensure_no_forbidden_keys(payload)
    except SystemExit as exc:
        assert "salary" in str(exc)
    else:
        raise AssertionError("Forbidden key was not rejected.")


def test_mock_server_respects_openapi_contract() -> None:
    with TestClient(mock_mapsi_app) as mock_client:
        health_response = mock_client.get("/health")
        capabilities_response = mock_client.get("/internal/growth/capabilities")
        usage_response = mock_client.get("/internal/growth/usage-snapshot")
        contact_response = mock_client.get("/internal/growth/contact-snapshot")
        changes_response = mock_client.get("/internal/growth/product-changes")

    assert health_response.status_code == 200
    assert capabilities_response.status_code == 200
    assert usage_response.status_code == 200
    assert contact_response.status_code == 200
    assert changes_response.status_code == 200
    jsonschema.validate(
        usage_response.json(),
        load_json(CONTRACTS / "usage-snapshot.schema.json"),
    )
    jsonschema.validate(
        contact_response.json(),
        load_json(CONTRACTS / "contact-snapshot.schema.json"),
    )
    jsonschema.validate(
        changes_response.json(),
        load_json(CONTRACTS / "product-change.schema.json"),
    )


def test_generated_client_is_typed_against_mock_server(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeHttpClient:
        def __init__(self, base_url: str, timeout: float, headers: dict | None = None) -> None:
            self.base_url = base_url
            self.timeout = timeout

        def get(self, path: str, params: dict | None = None) -> FakeResponse:
            file_map = {
                "/health": "health.example.json",
                "/internal/growth/capabilities": "capabilities.example.json",
                "/internal/growth/usage-snapshot": "usage-snapshot.example.json",
                "/internal/growth/contact-snapshot": "contact-snapshot.example.json",
                "/api/internal/growth/v1/product-changes": "product-change.example.json",
            }
            payload = json.loads((CONTRACTS / "examples" / file_map[path]).read_text(encoding="utf-8"))
            return FakeResponse(payload)

    monkeypatch.setattr("app.generated.mapsi_contract_client.Client", FakeHttpClient)
    client = MapsiContractClient("http://mock")

    health = client.get_health()
    capabilities = client.get_capabilities()
    usage = client.get_usage_snapshot(page_size=50)
    contacts = client.get_contact_snapshot(page_size=50)
    changes = client.get_product_changes()

    assert health.instance_id == "gpmlm"
    assert capabilities.capabilities[0].capability_key == "planning"
    assert usage.users[0].tenant_id == "tenant_alpha"
    assert usage.users[0].role_key == "manager"
    assert contacts.contacts[0].communication_eligible is True
    assert changes.contract_version == "1.0.0"
    assert changes.items[0].id == "MAPSI-2026-010"


def test_startup_logs_contract_sha(caplog) -> None:
    caplog.clear()
    caplog.set_level("INFO", logger="app.main")
    with TestClient(create_app()):
        pass
    assert "MAPSI contract loaded" in caplog.text
