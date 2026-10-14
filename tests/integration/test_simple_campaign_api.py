import os
from uuid import uuid4

from app.domain.entities import CampaignRun
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from tests.support_auth import auth_headers


def test_simple_campaign_uses_expected_test_database(session) -> None:
    expected = os.environ.get("GROWTH_TEST_EXPECTED_DIALECT")
    if not expected:
        return
    assert session.bind is not None
    assert session.bind.dialect.name == expected
    if expected == "postgresql":
        assert "phase7" in str(session.bind.url.database)


def approve_all_assets(client, campaign_id: str, assets: list[dict]) -> dict:
    approved = None
    for asset in assets:
        if asset.get("approved_version") == asset["version"] and asset.get("status") == "APPROVED":
            approved = {"content_assets": assets, "status": "APPROVED"}
            continue
        review_response = client.post(
            f"/studio-simple/campaigns/{campaign_id}/assets/{asset['id']}/review",
            headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
            json={"comment": "Reviewed in test", "expected_version": asset["version"]},
        )
        assert review_response.status_code == 200
        reviewed_asset = next(item for item in review_response.json()["content_assets"] if item["id"] == asset["id"])
        approve_response = client.post(
            f"/studio-simple/campaigns/{campaign_id}/assets/{asset['id']}/approve",
            headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
            json={"comment": "Approved in test", "expected_version": reviewed_asset["version"]},
        )
        assert approve_response.status_code == 200
        approved = approve_response.json()
    assert approved is not None
    return approved


def test_simple_campaign_lifecycle(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Communication ete",
            "campaign_type": "MAPSI_MARKETING",
            "theme": "Simplifier la communication produit",
            "selected_channels": ["mapsi_site", "oling_site", "linkedin_manual", "email_manual"],
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
    assert payload["status"] == "READY_FOR_REVIEW"
    assert len(payload["content_assets"]) == 4
    assert {asset["channel"] for asset in payload["content_assets"]} == {"mapsi_site", "oling_site", "linkedin_manual", "email_manual"}
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
    email_asset_initial = next(asset for asset in payload["content_assets"] if asset["channel"] == "email_manual")
    assert email_asset_initial["title"] == "Communication MAPSI : Simplifier la communication produit"
    assert "Objet :" in email_asset_initial["content_text"]
    assert "Bien cordialement," in email_asset_initial["content_text"]

    regenerate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert regenerate_response.status_code == 200
    regenerated = regenerate_response.json()
    assert regenerated["status"] == "READY_FOR_REVIEW"
    assert len(regenerated["content_assets"]) == 4

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

    stale_update_response = client.put(
        f"/studio-simple/campaigns/{campaign_id}/assets/{linkedin_asset['id']}",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "title": "LinkedIn stale",
            "content_text": "Version obsolete.",
            "expected_version": linkedin_asset["version"],
        },
    )
    assert stale_update_response.status_code == 409

    publish_without_approval = client.post(
        f"/studio-simple/campaigns/{campaign_id}/publish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["mapsi_site"]},
    )
    assert publish_without_approval.status_code == 409

    refreshed = client.get(
        f"/studio-simple/campaigns/{campaign_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    assert refreshed.status_code == 200
    approved_payload = approve_all_assets(client, campaign_id, refreshed.json()["content_assets"])
    assert approved_payload["status"] == "APPROVED"
    approved_linkedin = next(asset for asset in approved_payload["content_assets"] if asset["channel"] == "linkedin_manual")
    edit_after_approval = client.put(
        f"/studio-simple/campaigns/{campaign_id}/assets/{approved_linkedin['id']}",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "title": "LinkedIn modifie apres approbation",
            "content_text": "Modification invalidant l'approbation.",
            "expected_version": approved_linkedin["version"],
        },
    )
    assert edit_after_approval.status_code == 200
    edited_linkedin = next(asset for asset in edit_after_approval.json()["content_assets"] if asset["id"] == approved_linkedin["id"])
    assert edited_linkedin["approved_version"] is None
    reapproved_payload = approve_all_assets(client, campaign_id, edit_after_approval.json()["content_assets"])
    assert reapproved_payload["status"] == "APPROVED"

    publish_partial = client.post(
        f"/studio-simple/campaigns/{campaign_id}/publish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["mapsi_site", "linkedin_manual", "email_manual"]},
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
    assert len(publish_final.json()["publications"]) == 4


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
            "selected_channels": ["mapsi_site", "linkedin_manual", "email_manual"],
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
            "selected_channels": ["mapsi_site", "linkedin_manual", "email_manual"],
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
    users_email = next(asset for asset in users_assets if asset["channel"] == "email_manual")
    assert "Ce sujet merite une communication de fond" in users_article["content_text"]
    assert "Visuel suggere :" in users_linkedin["content_text"]
    assert "Objet :" in users_email["content_text"]

    oling_campaign = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Conseil Oling",
            "campaign_type": "OLING",
            "selected_channels": ["oling_site", "linkedin_manual", "email_manual"],
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
    oling_email = next(asset for asset in oling_assets if asset["channel"] == "email_manual")
    assert "Chez OLING, l'approche se structure autour de" in oling_article["content_text"]
    assert "Visuel suggere :" in oling_linkedin["content_text"]
    assert "Objet :" in oling_email["content_text"]
    assert oling_article["content_text"] != users_article["content_text"]


def test_openapi_exposes_simple_studio_and_legacy_admin_workflows(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    assert "/studio-simple/campaigns" in paths
    assert "/studio-simple/campaigns/{campaign_id}/generate" in paths
    assert "/studio-simple/campaigns/{campaign_id}/assets/{asset_id}/review" in paths
    assert "/studio-simple/campaigns/{campaign_id}/assets/{asset_id}/approve" in paths
    assert "/studio-simple/campaigns/{campaign_id}/archive" in paths
    assert "/studio-simple/campaigns/{campaign_id}/unpublish" in paths
    assert "/api/admin/v1/campaigns" in paths
    assert "/api/admin/v1/campaigns/{campaignId}" in paths
    assert "/api/admin/v1/weekly-packs" in paths
    assert "/api/admin/v1/source-packs/{id}" in paths
    assert "/api/admin/v1/channels" in paths
    assert "/api/admin/v1/assets/{assetId}/publish" in paths
    assert "/campaigns" in paths
    assert "/ops/campaigns/{campaign_id}/request-approval" in paths

    assert client.get("/studio-simple/campaigns").status_code == 401
    assert client.get("/api/admin/v1/campaigns").status_code == 401
    simple_response = client.get(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    legacy_response = client.get(
        "/api/admin/v1/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    audit_forbidden = client.get(
        "/api/admin/v1/audit-events",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    audit_allowed = client.get(
        "/api/admin/v1/audit-events",
        headers=auth_headers(roles=["ROLE_GROWTH_AUDIT"], jti=str(uuid4())),
    )
    assert simple_response.status_code == 200
    assert legacy_response.status_code == 200
    assert audit_forbidden.status_code == 403
    assert audit_allowed.status_code == 200


def test_simple_campaign_can_be_deleted_before_publication(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Campagne a supprimer",
            "campaign_type": "MAPSI_MARKETING",
            "theme": "Supprimer une ancienne campagne",
            "selected_channels": ["mapsi_site", "oling_site"],
        },
    )
    assert create_response.status_code == 201
    campaign_id = create_response.json()["id"]

    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 200

    delete_response = client.delete(
        f"/studio-simple/campaigns/{campaign_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    assert delete_response.status_code == 204

    get_response = client.get(
        f"/studio-simple/campaigns/{campaign_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    assert get_response.status_code == 404


def test_simple_campaign_archive_and_unpublish_are_explicit(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Campagne publiee",
            "campaign_type": "MAPSI_MARKETING",
            "theme": "Archiver sans supprimer",
            "selected_channels": ["mapsi_site", "oling_site"],
        },
    )
    assert create_response.status_code == 201
    campaign_id = create_response.json()["id"]
    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 200
    approve_all_assets(client, campaign_id, generate_response.json()["content_assets"])
    publish_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/publish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["mapsi_site", "oling_site"]},
    )
    assert publish_response.status_code == 200

    delete_response = client.delete(
        f"/studio-simple/campaigns/{campaign_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    assert delete_response.status_code == 409

    unpublish_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/unpublish",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        json={"channels": ["mapsi_site"]},
    )
    assert unpublish_response.status_code == 200
    unpublished_payload = unpublish_response.json()
    assert unpublished_payload["status"] == "PARTIALLY_PUBLISHED"
    channel_statuses = {asset["channel"]: asset["status"] for asset in unpublished_payload["content_assets"]}
    assert channel_statuses["mapsi_site"] == "APPROVED"
    assert channel_statuses["oling_site"] == "PUBLISHED"

    archive_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/archive",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "ARCHIVED"
    list_response = client.get("/studio-simple/campaigns", headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())))
    assert all(item["id"] != campaign_id for item in list_response.json())


def test_simple_campaign_sanitizes_edited_html(client) -> None:
    create_response = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "name": "Sanitation HTML",
            "campaign_type": "OLING",
            "theme": "Controle XSS synthétique",
            "selected_channels": ["oling_site"],
        },
    )
    assert create_response.status_code == 201
    campaign_id = create_response.json()["id"]
    generate_response = client.post(
        f"/studio-simple/campaigns/{campaign_id}/generate",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    assert generate_response.status_code == 200
    asset = generate_response.json()["content_assets"][0]

    update_response = client.put(
        f"/studio-simple/campaigns/{campaign_id}/assets/{asset['id']}",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={
            "title": "HTML nettoye",
            "content_html": '<h2 onclick="alert(1)">Titre</h2><script>alert(1)</script><a href="javascript:alert(1)">Lien</a>',
            "content_text": "Texte propre",
            "expected_version": asset["version"],
        },
    )
    assert update_response.status_code == 200
    updated_asset = update_response.json()["content_assets"][0]
    assert "<script" not in updated_asset["content_html"]
    assert "onclick" not in updated_asset["content_html"]
    assert "javascript:" not in updated_asset["content_html"]


def test_simple_campaign_api_rejects_unauthorized_forbidden_and_invalid_requests(client) -> None:
    missing_token = client.get("/studio-simple/campaigns")
    assert missing_token.status_code == 401

    expired_token = client.get(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4()), expires_delta_seconds=-1000),
    )
    assert expired_token.status_code == 401

    forbidden = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
        json={
            "name": "Refus droits",
            "campaign_type": "OLING",
            "theme": "Controle droits",
            "selected_channels": ["oling_site"],
        },
    )
    assert forbidden.status_code == 403

    invalid_payload = client.post(
        "/studio-simple/campaigns",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
        json={"name": "Payload invalide"},
    )
    assert invalid_payload.status_code == 422

    not_found = client.get(
        "/studio-simple/campaigns/unknown",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    assert not_found.status_code == 404
