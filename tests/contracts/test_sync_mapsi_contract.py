from __future__ import annotations

from pathlib import Path

import yaml

from scripts import sync_mapsi_contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts" / "mapsi"
GENERATED = ROOT / "app" / "generated"


class FakeResponse:
    def __init__(self, text: str | None = None, payload: dict | None = None) -> None:
        self.text = text or ""
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.fixtures = {
            "openapi.yaml": (CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"),
            "usage-snapshot.schema.json": (CONTRACTS / "usage-snapshot.schema.json").read_text(encoding="utf-8"),
            "contact-snapshot.schema.json": (CONTRACTS / "contact-snapshot.schema.json").read_text(encoding="utf-8"),
            "product-change.schema.json": (CONTRACTS / "product-change.schema.json").read_text(encoding="utf-8"),
            "examples/health.example.json": (CONTRACTS / "examples" / "health.example.json").read_text(encoding="utf-8"),
            "examples/capabilities.example.json": (CONTRACTS / "examples" / "capabilities.example.json").read_text(encoding="utf-8"),
            "examples/usage-snapshot.example.json": (CONTRACTS / "examples" / "usage-snapshot.example.json").read_text(encoding="utf-8"),
            "examples/contact-snapshot.example.json": (CONTRACTS / "examples" / "contact-snapshot.example.json").read_text(encoding="utf-8"),
            "examples/product-change.example.json": (CONTRACTS / "examples" / "product-change.example.json").read_text(encoding="utf-8"),
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str) -> FakeResponse:
        if "/commits/" in url:
            return FakeResponse(payload={"sha": "2222222222222222222222222222222222222222"})
        marker = "/docs/growth-contract/published/"
        relative = url.split(marker, 1)[1]
        return FakeResponse(text=self.fixtures[relative])


def test_sync_script_writes_contract_version_and_generated_files(monkeypatch, tmp_path) -> None:
    contract_dir = tmp_path / "contracts" / "mapsi"
    generated_dir = tmp_path / "app" / "generated"
    contract_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    monkeypatch.setattr(sync_mapsi_contract, "CONTRACTS_DIR", contract_dir)
    monkeypatch.setattr(sync_mapsi_contract, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(sync_mapsi_contract.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_mapsi_contract.py",
            "--repo",
            "mapsi/mapsi-v6",
            "--branch",
            "release/1.2",
        ],
    )

    result = sync_mapsi_contract.main()

    assert result == 0
    assert "source_sha=2222222222222222222222222222222222222222" in (
        contract_dir / "contract-version.txt"
    ).read_text(encoding="utf-8")
    assert (generated_dir / "mapsi_contract_models.py").exists()
    assert (generated_dir / "mapsi_contract_client.py").exists()


def test_sync_script_rejects_incompatible_major_version(monkeypatch, tmp_path) -> None:
    contract_dir = tmp_path / "contracts" / "mapsi"
    generated_dir = tmp_path / "app" / "generated"
    contract_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)

    class IncompatibleClient(FakeClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            openapi = yaml.safe_load(self.fixtures["openapi.yaml"])
            openapi["info"]["version"] = "2.0.0"
            self.fixtures["openapi.yaml"] = yaml.safe_dump(openapi, sort_keys=False)

    monkeypatch.setattr(sync_mapsi_contract, "CONTRACTS_DIR", contract_dir)
    monkeypatch.setattr(sync_mapsi_contract, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(sync_mapsi_contract.httpx, "Client", IncompatibleClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_mapsi_contract.py",
            "--repo",
            "mapsi/mapsi-v6",
            "--tag",
            "v2.0.0",
        ],
    )

    try:
        sync_mapsi_contract.main()
    except SystemExit as exc:
        assert "Incompatible contract major version" in str(exc)
    else:
        raise AssertionError("Expected major version rejection.")
