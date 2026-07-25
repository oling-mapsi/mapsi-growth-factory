from uuid import uuid4

from app.domain.entities import CampaignRun
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from tests.support_auth import auth_headers


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
    mapsi_asset = next(asset for asset in payload["content_assets"] if asset["channel"] == "mapsi_site")
    assert len(mapsi_asset["content_text"]) > 400
    assert "<ul>" in mapsi_asset["content_html"]
    assert mapsi_asset["illustration_suggestion"] != ""
    assert mapsi_asset["call_to_action"] != ""
    assert "Ce sujet merite une communication de fond" in mapsi_asset["content_text"]

    oling_asset = next(asset for asset in payload["content_assets"] if asset["channel"] == "oling_site")
    assert len(oling_asset["content_text"]) > 400
    assert oling_asset["content_text"] != mapsi_asset["content_text"]

    linkedin_asset_initial = next(asset for asset in payload["content_assets"] if asset["channel"] == "linkedin_manual")
    assert "Visuel suggere :" in linkedin_asset_initial["content_text"]

    regenerate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert regenerate_response.status_code == 200
    regenerated = regenerate_response.json()
    assert regenerated["status"] == "READY"
    assert len(regenerated["content_assets"]) == 3

    linkedin_asset = next(asset for asset in regenerated["content_assets"] if asset["channel"] == "linkedin_manual")
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


def test_simple_campaign_hides_legacy_campaigns(client, session) -> None:
    campaign_id = SqlAlchemyCampaignRepository(session).add(
        CampaignRun(name="Legacy", objective="Legacy objective", workflow_kind="LEGACY")
    ).id

    list_response = client.get("/studio-simple/campaigns", headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())))
    assert list_response.status_code == 200
    assert all(item["id"] != campaign_id for item in list_response.json())

    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 404


def test_oling_theme_catalog_and_validation(client) -> None:
    catalog = client.get("/studio-simple/oling-themes", headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())))
    assert catalog.status_code == 200
    assert "rgpd-et-dpo" in catalog.json()["items"]

    valid_free_theme = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Oling libre",
            "campaign_type": "OLING",
            "theme": "theme-inconnu",
            "selected_channels": ["oling_site"],
        },
    )
    assert valid_free_theme.status_code == 201


def test_simple_campaign_generates_theme_when_missing(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Campagne sans theme",
            "campaign_type": "MAPSI_USERS",
            "selected_channels": ["mapsi_site", "linkedin_manual"],
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["theme"] != ""


def test_simple_campaign_uses_distinct_tone_for_users_and_oling(client) -> None:
    users_campaign = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Usage quotidien",
            "campaign_type": "MAPSI_USERS",
            "selected_channels": ["mapsi_site", "linkedin_manual"],
        },
    )
    assert users_campaign.status_code == 201
    users_id = users_campaign.json()["id"]
    users_generated = client.post(
        f"/studio-simple/campaigns/{users_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert users_generated.status_code == 200
    users_assets = users_generated.json()["content_assets"]
    users_article = next(asset for asset in users_assets if asset["channel"] == "mapsi_site")
    users_linkedin = next(asset for asset in users_assets if asset["channel"] == "linkedin_manual")
    assert "Ce sujet merite une communication de fond" in users_article["content_text"]
    assert "Visuel suggere :" in users_linkedin["content_text"]

    oling_campaign = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Conseil Oling",
            "campaign_type": "OLING",
            "selected_channels": ["oling_site", "linkedin_manual"],
        },
    )
    assert oling_campaign.status_code == 201
    oling_id = oling_campaign.json()["id"]
    oling_generated = client.post(
        f"/studio-simple/campaigns/{oling_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert oling_generated.status_code == 200
    oling_assets = oling_generated.json()["content_assets"]
    oling_article = next(asset for asset in oling_assets if asset["channel"] == "oling_site")
    oling_linkedin = next(asset for asset in oling_assets if asset["channel"] == "linkedin_manual")
    assert "Chez OLING, l'approche se structure autour de" in oling_article["content_text"]
    assert "Visuel suggere :" in oling_linkedin["content_text"]
    assert oling_article["content_text"] != users_article["content_text"]


def test_openapi_prioritizes_simple_studio_and_hides_legacy_admin_workflows(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    assert "/studio-simple/campaigns" in paths
    assert "/studio-simple/campaigns/{campaign_id}/generate" in paths
    assert "/api/admin/v1/campaigns" not in paths
    assert "/api/admin/v1/campaigns/{campaignId}" not in paths
    assert "/api/admin/v1/weekly-packs" not in paths
    assert "/api/admin/v1/source-packs" not in paths
    assert "/api/admin/v1/channels" not in paths
    assert "/api/admin/v1/assets/{assetId}/publish" not in paths
    assert "/campaigns" not in paths
    assert "/ops/campaigns/{campaign_id}/request-approval" not in paths
