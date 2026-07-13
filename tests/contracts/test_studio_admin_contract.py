from pathlib import Path

import yaml

from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "studio-admin" / "openapi.yaml"


def test_studio_admin_openapi_contract_exists_and_covers_expected_paths() -> None:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert payload["info"]["version"] == "1.0.0"
    assert set(payload["paths"]) == {
        "/api/admin/v1/dashboard",
        "/api/admin/v1/weekly-packs",
        "/api/admin/v1/weekly-packs/{id}",
        "/api/admin/v1/weekly-packs/{id}/generate",
        "/api/admin/v1/weekly-packs/{id}/close",
        "/api/admin/v1/source-packs",
        "/api/admin/v1/source-packs/{id}",
        "/api/admin/v1/source-packs/{id}/validate",
        "/api/admin/v1/source-packs/{id}/items",
        "/api/admin/v1/source-packs/{id}/items/{itemId}",
        "/api/admin/v1/source-packs/{id}/editorial-preview",
        "/api/admin/v1/campaigns",
        "/api/admin/v1/campaigns/{campaignId}",
        "/api/admin/v1/campaigns/{campaignId}/assets",
        "/api/admin/v1/assets/{assetId}",
        "/api/admin/v1/assets/{assetId}/versions",
        "/api/admin/v1/assets/{assetId}/evidence",
        "/api/admin/v1/assets/{assetId}/preview",
        "/api/admin/v1/assets/{assetId}/publication",
        "/api/admin/v1/assets/{assetId}/draft",
        "/api/admin/v1/assets/{assetId}/request-regeneration",
        "/api/admin/v1/assets/{assetId}/request-changes",
        "/api/admin/v1/assets/{assetId}/approve",
        "/api/admin/v1/assets/{assetId}/reject",
        "/api/admin/v1/assets/{assetId}/publication-readiness",
        "/api/admin/v1/assets/{assetId}/create-preview",
        "/api/admin/v1/assets/{assetId}/schedule",
        "/api/admin/v1/assets/{assetId}/publish",
        "/api/admin/v1/assets/{assetId}/cancel-publication",
        "/api/admin/v1/assets/{assetId}/retry-publication",
        "/api/admin/v1/assets/{assetId}/unpublish",
        "/api/admin/v1/assets/{assetId}/publication-status",
        "/api/admin/v1/campaigns/{campaignId}/approve-ready-assets",
        "/api/admin/v1/campaigns/{campaignId}/reject-ready-assets",
        "/api/admin/v1/channels",
        "/api/admin/v1/channels/{channel}",
        "/api/admin/v1/channels/{channel}/health-check",
        "/api/admin/v1/channels/{channel}/enable",
        "/api/admin/v1/channels/{channel}/disable",
        "/api/admin/v1/channels/{channel}/activate-kill-switch",
        "/api/admin/v1/channels/{channel}/deactivate-kill-switch",
        "/api/admin/v1/global-kill-switch/activate",
        "/api/admin/v1/global-kill-switch/deactivate",
        "/api/admin/v1/audit-events",
        "/api/admin/v1/audit-events/export.csv",
        "/api/admin/v1/health",
    }


def test_studio_admin_generated_contract_matches_live_openapi_subset() -> None:
    app = create_app()
    live = app.openapi()
    live_paths = {key: value for key, value in live["paths"].items() if key.startswith("/api/admin/v1")}
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    assert contract["paths"] == live_paths


def test_studio_admin_contract_contains_synthetic_examples() -> None:
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    schemas = payload["components"]["schemas"]
    assert "example" in schemas["StudioAdminDashboardResponse"]
    assert "example" in schemas["StudioAdminCampaignResponse"]
    assert "example" in schemas["StudioAdminAssetResponse"]
    assert "example" in schemas["StudioAdminPublicationResponse"]
    assert "example" in schemas["StudioAdminWeeklyPackResponse"]
    assert "example" in schemas["StudioAdminEditorialSourcePackResponse"]
    assert "example" in schemas["StudioAdminChannelResponse"]
    assert "example" in schemas["StudioAdminGlobalKillSwitchResponse"]
    assert "example" in schemas["StudioAdminAuditEventResponse"]
