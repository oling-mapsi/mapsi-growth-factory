from uuid import uuid4

from tests.integration.test_studio_admin_api import auth_headers


def legacy_auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def test_simple_campaign_lifecycle(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Communication ete",
            "campaign_type": "MAPSI_MARKETING",
            "theme": "Simplifier la communication produit",
            "selected_channels": ["mapsi_site", "oling_site", "linkedin_manual"],
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["status"] == "DRAFT"
    campaign_id = payload["id"]

    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["status"] == "READY"
    assert len(payload["content_assets"]) == 3
    assert {asset["channel"] for asset in payload["content_assets"]} == {"mapsi_site", "oling_site", "linkedin_manual"}

    linkedin_asset = next(asset for asset in payload["content_assets"] if asset["channel"] == "linkedin_manual")
    update_response = client.put(
        f"/studio-simple/campaigns/{campaign_id}/assets/{linkedin_asset['id']}",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "title": "LinkedIn manuel",
            "content_text": "Version courte retravaillee pour LinkedIn.",
            "expected_version": linkedin_asset["version"],
        },
    )
    assert update_response.status_code == 200
    updated_asset = next(asset for asset in update_response.json()["content_assets"] if asset["id"] == linkedin_asset["id"])
    assert updated_asset["title"] == "LinkedIn manuel"
    assert updated_asset["version"] == linkedin_asset["version"] + 1

    publish_partial = client.post(
        f"/studio-simple/campaigns/{campaign_id}/publish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["mapsi_site", "linkedin_manual"]},
    )
    assert publish_partial.status_code == 200
    assert publish_partial.json()["status"] == "PARTIALLY_PUBLISHED"

    publish_final = client.post(
        f"/studio-simple/campaigns/{campaign_id}/publish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["oling_site"]},
    )
    assert publish_final.status_code == 200
    assert publish_final.json()["status"] == "PUBLISHED"
    assert len(publish_final.json()["publications"]) == 3


def test_simple_campaign_legacy_is_read_only(client) -> None:
    create_legacy = client.post(
        "/campaigns",
        headers=legacy_auth_headers(),
        json={
            "name": "Legacy",
            "objective": "Legacy objective",
            "audience": {"name": "CMO", "description": "legacy"},
        },
    )
    assert create_legacy.status_code == 201
    campaign_id = create_legacy.json()["id"]

    list_response = client.get("/studio-simple/campaigns", headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())))
    assert list_response.status_code == 200
    legacy = next(item for item in list_response.json() if item["id"] == campaign_id)
    assert legacy["legacy_read_only"] is True

    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 409


def test_oling_theme_catalog_and_validation(client) -> None:
    catalog = client.get("/studio-simple/oling-themes", headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())))
    assert catalog.status_code == 200
    assert "rgpd-et-dpo" in catalog.json()["items"]

    invalid = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Oling invalide",
            "campaign_type": "OLING",
            "theme": "theme-inconnu",
            "selected_channels": ["oling_site"],
        },
    )
    assert invalid.status_code == 409


def test_openapi_prioritizes_simple_studio_and_hides_legacy_admin_workflows(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    assert "/studio-simple/campaigns" in paths
    assert "/studio-simple/campaigns/{campaign_id}/generate" in paths
    assert "/api/admin/v1/campaigns" in paths
    assert "/api/admin/v1/campaigns/{campaignId}" in paths
    assert "/api/admin/v1/weekly-packs" not in paths
    assert "/api/admin/v1/source-packs" not in paths
    assert "/api/admin/v1/channels" not in paths
    assert "/api/admin/v1/assets/{assetId}/publish" not in paths
