from __future__ import annotations

from types import SimpleNamespace

from app.application.services.editorial_autopublish_v1 import EditorialAutopublishService
from app.core.config import get_settings
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief
from app.domain.enums import AssetStatus, CampaignStatus


def _asset(*, asset_id: str, channel: str, title: str = "Article", passed: bool = True, warnings=None, errors=None, verified: bool = True, has_sources: bool = True):
    warnings = warnings or []
    errors = errors or []
    asset = ContentAsset(
        id=asset_id,
        campaign_run_id="campaign-1",
        asset_type="mapsi_news_article" if channel == "mapsi_site" else "oling_news_article",
        channel=channel,
        title=title,
        content_html="<p>Contenu suffisamment long pour passer les controles deterministes.</p>" * 4,
        content_text="Contenu suffisamment long pour passer les controles deterministes. " * 4,
        excerpt="Extrait",
        call_to_action="Demander un echange",
        target_url="https://www.example.test/article",
        source_evidence_ids=["src-1"] if has_sources else [],
        audience_segment_id=channel,
        status=AssetStatus.READY_FOR_REVIEW,
        results={
            "editorial_article": {
                "claims": [{"verified": verified}],
            },
            "editorial_quality": {
                "passed": passed,
                "issues": warnings + errors,
            },
            "editorial_execution": {
                "knowledge_version": "kv-1",
                "cost_usd": 0.12,
            },
        },
    )
    asset.ensure_content_hash()
    return asset


def _campaign(campaign_id: str, campaign_type: str, assets: list[ContentAsset]) -> CampaignRun:
    campaign = CampaignRun(id=campaign_id, name=campaign_type, objective="editorial", campaign_type=campaign_type, status=CampaignStatus.READY_FOR_REVIEW)
    campaign.editorial_briefs = [EditorialBrief(campaign_run_id=campaign.id, title=f"{campaign_type} topic", summary="summary")]
    for asset in assets:
        asset.campaign_run_id = campaign.id
    campaign.content_assets = assets
    return campaign


class _FakeRepo:
    def save(self, campaign):
        return campaign


class _FakeCampaignService:
    def __init__(self, campaigns):
        self._campaigns = campaigns
        self.repository = _FakeRepo()

    def get_campaign(self, campaign_id):
        return self._campaigns[campaign_id]


class _FakeStudioAdminService:
    def __init__(self, campaigns, *, channel_enabled=True, global_kill_switch=False, timeout_asset_id: str = "", fail_asset_id: str = "", existing_published_asset_id: str = ""):
        self._campaigns = campaigns
        self.campaign_service = _FakeCampaignService(campaigns)
        self._channel_enabled = channel_enabled
        self._global_kill_switch = global_kill_switch
        self._timeout_asset_id = timeout_asset_id
        self._fail_asset_id = fail_asset_id
        self._existing_published_asset_id = existing_published_asset_id
        self._publications = {}

    def generate_mapsi_market(self, *, actor: str, correlation_id: str):
        return SimpleNamespace(id="campaign-mapsi")

    def generate_oling_practice(self, *, actor: str, correlation_id: str):
        return SimpleNamespace(id="campaign-oling")

    def create_asset_preview(self, asset_id: str, *, actor: str, correlation_id: str):
        return SimpleNamespace(preview_url=f"https://preview.test/{asset_id}", status="preview_ready")

    def get_asset_publication(self, asset_id: str):
        publication = self._publications.get(asset_id, {})
        if asset_id == self._existing_published_asset_id and not publication:
            publication = {
                "publication_status": "PUBLISHED",
                "idempotency_key": "existing-key",
                "external_publication_url": f"https://public.test/{asset_id}",
                "published_at": None,
                "metadata": {},
            }
        return SimpleNamespace(
            publication_status=publication.get("publication_status", "DRAFT"),
            idempotency_key=publication.get("idempotency_key", ""),
            external_publication_url=publication.get("external_publication_url", ""),
            published_at=publication.get("published_at"),
            metadata=publication.get("metadata", {}),
        )

    def publish_asset_operation(self, asset_id: str, *, actor: str, correlation_id: str, idempotency_key: str):
        if asset_id == self._timeout_asset_id:
            self._publications[asset_id] = {
                "publication_status": "PUBLISHED",
                "idempotency_key": idempotency_key,
                "external_publication_url": f"https://public.test/{asset_id}",
                "published_at": None,
                "metadata": {"preview_url": f"https://preview.test/{asset_id}"},
            }
            raise RuntimeError("timeout after publish")
        if asset_id == self._fail_asset_id:
            raise RuntimeError("remote failure")
        self._publications[asset_id] = {
            "publication_status": "PUBLISHED",
            "idempotency_key": idempotency_key,
            "external_publication_url": f"https://public.test/{asset_id}",
            "published_at": None,
            "metadata": {"preview_url": f"https://preview.test/{asset_id}"},
        }
        return SimpleNamespace(
            status="published",
            preview_url=f"https://preview.test/{asset_id}",
            public_url=f"https://public.test/{asset_id}",
            published_at=None,
        )

    def get_channel(self, channel: str):
        return SimpleNamespace(enabled=self._channel_enabled, emergency_kill_switch=False, configured=True, last_error="")

    def get_global_kill_switch(self):
        return SimpleNamespace(active=self._global_kill_switch)

    def return_to_safe_mode(self, *, actor: str, correlation_id: str):
        return {"global_kill_switch": {"after": True}, "channels": [{"channel": "oling", "feature_enabled": False}]}


def _service(monkeypatch, studio_service):
    monkeypatch.setenv("AUTO_PUBLISH_WEB_ENABLED", "true")
    monkeypatch.setenv("AUTO_PUBLISH_MAPSI_MARKET", "true")
    monkeypatch.setenv("AUTO_PUBLISH_OLING_PRACTICE", "true")
    monkeypatch.delenv("AUTO_PUBLISH_MIN_QUALITY_SCORE", raising=False)
    monkeypatch.setenv("AUTO_PUBLISH_BLOCK_ON_WARNING", "true")
    get_settings.cache_clear()
    return EditorialAutopublishService(studio_service)


def test_quality_refused_blocks_publication(monkeypatch):
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling", passed=False), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns)).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    mapsi_checks = result["campaigns"][0]["result"]["checks"]
    assert "quality_refused" in mapsi_checks[0]["blocking_reasons"]


def test_warning_blocking_blocks_publication(monkeypatch):
    warning = {"code": "tone", "severity": "warning"}
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling", warnings=[warning]), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns)).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    assert "blocking_warning" in result["campaigns"][0]["result"]["checks"][0]["blocking_reasons"]


def test_missing_sources_and_duplicate_are_blocked(monkeypatch):
    duplicate = {"code": "content_too_similar", "severity": "error"}
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling", has_sources=False, errors=[duplicate]), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns)).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    reasons = result["campaigns"][0]["result"]["checks"][0]["blocking_reasons"]
    assert "missing_sources" in reasons
    assert "duplicate" in reasons


def test_channel_disabled_and_kill_switch_block(monkeypatch):
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling"), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result_channel = _service(monkeypatch, _FakeStudioAdminService(campaigns, channel_enabled=False)).run_weekly(mode="publish", actor="cli", correlation_id="c1")
    assert "channel_disabled" in result_channel["campaigns"][0]["result"]["checks"][0]["blocking_reasons"]

    result_global = _service(monkeypatch, _FakeStudioAdminService(campaigns, global_kill_switch=True)).run_weekly(mode="publish", actor="cli", correlation_id="c1")
    assert "global_kill_switch" in result_global["campaigns"][0]["result"]["checks"][0]["blocking_reasons"]


def test_oling_publication_success(monkeypatch):
    monkeypatch.setenv("AUTO_PUBLISH_WEB_ENABLED", "true")
    monkeypatch.setenv("AUTO_PUBLISH_MAPSI_MARKET", "false")
    monkeypatch.setenv("AUTO_PUBLISH_OLING_PRACTICE", "true")
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling"), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    get_settings.cache_clear()
    result = EditorialAutopublishService(_FakeStudioAdminService(campaigns)).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    publications = result["campaigns"][1]["result"]["publications"]
    assert len(publications) == 1
    assert publications[0]["public_url"] == "https://public.test/a3"


def test_mapsi_market_publication_success(monkeypatch):
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling"), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns)).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    publications = result["campaigns"][0]["result"]["publications"]
    assert len(publications) == 2
    assert {item["channel"] for item in publications} == {"oling", "mapsi_site"}


def test_partial_publication_sets_alert(monkeypatch):
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling"), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns, fail_asset_id="a2")).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    assert result["campaigns"][0]["result"]["partial_alert"] is True
    assert len(result["campaigns"][0]["result"]["publications"]) == 1


def test_timeout_and_already_published_are_recovered(monkeypatch):
    campaigns = {
        "campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", [_asset(asset_id="a1", channel="oling"), _asset(asset_id="a2", channel="mapsi_site")]),
        "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [_asset(asset_id="a3", channel="oling")]),
    }
    result = _service(monkeypatch, _FakeStudioAdminService(campaigns, timeout_asset_id="a2", existing_published_asset_id="a3")).run_weekly(mode="publish", actor="cli", correlation_id="c1")

    mapsi_publications = result["campaigns"][0]["result"]["publications"]
    oling_publications = result["campaigns"][1]["result"]["publications"]
    assert any(item["replay"] is True for item in mapsi_publications)
    assert oling_publications[0]["already_published"] is True


def test_return_to_safe_mode_reports_disabled_flags(monkeypatch):
    service = _service(monkeypatch, _FakeStudioAdminService({"campaign-mapsi": _campaign("campaign-mapsi", "MAPSI_MARKET", []), "campaign-oling": _campaign("campaign-oling", "OLING_PRACTICE", [])}))

    report = service.return_to_safe_mode(actor="cli", correlation_id="c1")

    assert report["flags_after"]["AUTO_PUBLISH_WEB_ENABLED"] is False
    assert report["global_controls"]["global_kill_switch"]["after"] is True
