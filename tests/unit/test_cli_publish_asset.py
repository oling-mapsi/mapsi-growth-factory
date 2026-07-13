import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app import cli
from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset, MapsiNewsPublication, SourceEvidence
from app.domain.enums import CampaignStatus
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.domain.entities import OlingNewsPublication
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


@dataclass
class _WeeklyCampaign:
    id: str
    campaign_type: str
    title: str
    status: str
    asset_count: int
    published_assets: int
    errors: list[str] = field(default_factory=list)


@dataclass
class _WeeklyPack:
    id: str
    week_reference: str
    year: int
    week_number: int
    status: str
    created_at: datetime
    generated_at: datetime | None
    reviewed_at: datetime | None
    completed_at: datetime | None
    campaign_ids: list[str]
    campaigns: list[_WeeklyCampaign]
    global_summary: dict[str, object] = field(default_factory=dict)
    operational_errors: list[dict[str, object]] = field(default_factory=list)
    pilot_mode: bool = True


def test_cli_publish_asset_dry_run_uses_oling_publisher(session, monkeypatch, capsys) -> None:
    campaign = CampaignRun(name="CLI campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="oling_news_article",
        channel="oling",
        title="CLI Article",
        content_html="<p>Body</p>",
        content_text="Body",
        audience_segment_id=campaign.audience_segments[0].id,
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    campaign.content_assets.append(asset)
    SqlAlchemyCampaignRepository(session).add(campaign)

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)

    class StubPublisher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def publish_asset(self, campaign_id: str, asset_id: str, *, dry_run: bool = False, idempotency_key: str = "") -> dict:
            return {"campaign_id": campaign_id, "asset_id": asset_id, "dry_run": dry_run, "channel": "oling"}

    monkeypatch.setattr(cli, "OlingNewsPublisher", StubPublisher)
    monkeypatch.setattr(cli, "build_oling_config", lambda: object())
    monkeypatch.setattr(cli, "OlingConnector", lambda config: object())
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {"command": "publish-asset", "asset_id": asset.id, "channel": "oling", "dry_run": True, "idempotency_key": ""},
        )(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["asset_id"] == asset.id


def test_cli_diagnose_asset_outputs_oling_state(session, monkeypatch, capsys) -> None:
    campaign = CampaignRun(name="CLI campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="oling_news_article",
        channel="oling",
        title="CLI Article",
        content_html="<p>Body</p>",
        content_text="Body",
        audience_segment_id=campaign.audience_segments[0].id,
        external_publication_id="asset-1",
        external_publication_url="https://www.oling.fr/ressources/cli-article",
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    campaign.content_assets.append(asset)
    SqlAlchemyCampaignRepository(session).add(campaign)
    OlingNewsPublicationRepository(session).save(
        OlingNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            publication_mode_requested="publish",
            publication_mode_executed="live",
            publisher_type="oling_api",
            publication_status="PUBLISHED",
            idempotency_key="diag-1",
            public_url="https://www.oling.fr/ressources/cli-article",
        )
    )
    SqlAlchemyAuditLogRepository(session).append(campaign.id, "campaign.oling_published", {"asset_id": asset.id})

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "diagnose-asset", "asset_id": asset.id, "channel": "oling"})(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["asset_id"] == asset.id
    assert payload["mode_requested"] == "publish"
    assert payload["mode_executed"] == "live"
    assert payload["publisher"] == "oling_api"
    assert payload["idempotency_key"] == "diag-1"


def test_cli_publish_asset_dry_run_uses_mapsi_site_publisher(session, monkeypatch, capsys) -> None:
    campaign = CampaignRun(name="CLI campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title="CLI Article",
        content_html="<p>Body</p>",
        content_text="Body",
        audience_segment_id=campaign.audience_segments[0].id,
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    campaign.content_assets.append(asset)
    SqlAlchemyCampaignRepository(session).add(campaign)

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)

    class StubPublisher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def publish_asset(self, campaign_id: str, asset_id: str, *, dry_run: bool = False, idempotency_key: str = "") -> dict:
            return {"campaign_id": campaign_id, "asset_id": asset_id, "dry_run": dry_run, "channel": "mapsi_site"}

    monkeypatch.setattr(cli, "_build_mapsi_publisher", lambda session: StubPublisher())
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type(
            "Args",
            (),
            {"command": "publish-asset", "asset_id": asset.id, "channel": "mapsi_site", "dry_run": True, "idempotency_key": ""},
        )(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["channel"] == "mapsi_site"


def test_cli_diagnose_asset_outputs_mapsi_site_state(session, monkeypatch, capsys) -> None:
    campaign = CampaignRun(name="CLI campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title="CLI Article",
        content_html="<p>Body</p>",
        content_text="Body",
        audience_segment_id=campaign.audience_segments[0].id,
        external_publication_id="1",
        external_publication_url="https://www.mapsi.fr/actualites/cli-article",
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    campaign.content_assets.append(asset)
    SqlAlchemyCampaignRepository(session).add(campaign)
    MapsiNewsPublicationRepository(session).save(
        MapsiNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id="1",
            content_hash=asset.content_hash,
            publication_mode_requested="publish",
            publication_mode_executed="live",
            publisher_type="mapsi_site_api",
            publication_status="PUBLISHED",
            idempotency_key="diag-mapsi-1",
            public_url="https://www.mapsi.fr/actualites/cli-article",
            metrics={"idempotent_replay": True, "correlation_id": "mapsi-correlation"},
        )
    )
    SqlAlchemyAuditLogRepository(session).append(campaign.id, "campaign.mapsi_site_published", {"asset_id": asset.id})

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "diagnose-asset", "asset_id": asset.id, "channel": "mapsi_site"})(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["asset_id"] == asset.id
    assert payload["asset_type"] == "mapsi_news_article"
    assert payload["publisher"] == "mapsi_site_api"
    assert payload["idempotency_key"] == "diag-mapsi-1"
    assert payload["idempotent_replay"] is True


def test_cli_mapsi_site_diagnose_outputs_sanitized_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.argparse.ArgumentParser, "parse_args", lambda self: type("Args", (), {"command": "mapsi-site:diagnose", "skip_preview_probe": False})())
    monkeypatch.setattr(
        cli,
        "_mapsi_site_diagnose",
        lambda **kwargs: {
            "target_url": "https://mapsi.fr",
            "configuration": {"configured": True},
            "authentication": {"ok": True},
            "health": {"ok": True},
            "contract": {"version": "1.0.0"},
            "preview_probe": {"executed": True},
        },
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract"]["version"] == "1.0.0"
    assert "token" not in json.dumps(payload).lower()


def test_cli_mapsi_site_recipe_preview_and_publish(session, monkeypatch, capsys) -> None:
    campaign = CampaignRun(name="CLI campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title="CLI Mapsi",
        content_html="<p>Body</p>",
        content_text="Body",
        audience_segment_id=campaign.audience_segments[0].id,
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    campaign.content_assets.append(asset)
    SqlAlchemyCampaignRepository(session).add(campaign)

    class StubPublisher:
        campaign_repository = SqlAlchemyCampaignRepository(session)

        def create_preview(self, campaign, asset):
            return {"preview_url": "http://testserver/preview/actualites/cli-mapsi?token=t"}

        def publish(self, campaign, asset):
            return type("Publication", (), {"channel": "mapsi_site", "external_reference": "1", "external_url": "https://www.mapsi.fr/actualites/cli-mapsi"})()

        def get_publication_status(self, campaign, asset):
            return {"publication_status": "PUBLISHED", "external_publication_id": "1"}

    monkeypatch.setattr(cli, "_build_mapsi_publisher", lambda session: StubPublisher())
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "mapsi-site:recipe", "asset_id": asset.id, "mode": "preview"})(),
    )
    assert cli.main() == 0
    preview_payload = json.loads(capsys.readouterr().out)
    assert preview_payload["mode"] == "preview"

    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "mapsi-site:recipe", "asset_id": asset.id, "mode": "publish"})(),
    )
    assert cli.main() == 0
    publish_payload = json.loads(capsys.readouterr().out)
    assert publish_payload["mode"] == "publish"
    assert publish_payload["publication"]["external_reference"] == "1"


def test_cli_weekly_generate_and_status_use_studio_admin_service(session, monkeypatch, capsys) -> None:
    pack = _WeeklyPack(
        id="pack-1",
        week_reference="2026-W29",
        year=2026,
        week_number=29,
        status="READY_FOR_REVIEW",
        created_at=datetime.now(UTC),
        generated_at=datetime.now(UTC),
        reviewed_at=None,
        completed_at=None,
        campaign_ids=["camp-1", "camp-2", "camp-3"],
        campaigns=[_WeeklyCampaign(id="camp-1", campaign_type="MAPSI_MARKET", title="Market", status="READY_FOR_REVIEW", asset_count=3, published_assets=0)],
    )

    class StubService:
        def generate_weekly_pack_campaign(self, pack_id, *, campaign_type, actor, correlation_id):
            assert pack_id == "pack-1"
            assert campaign_type == "MAPSI_MARKET"
            return pack

        def get_weekly_pack(self, pack_id):
            assert pack_id == "pack-1"
            return pack

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(cli, "_build_studio_admin_service", lambda session: StubService())
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "weekly:generate", "pack_id": "pack-1", "campaign": "MAPSI_MARKET"})(),
    )

    assert cli.main() == 0
    generated_payload = json.loads(capsys.readouterr().out)
    assert generated_payload["id"] == "pack-1"
    assert generated_payload["campaigns"][0]["campaign_type"] == "MAPSI_MARKET"

    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "weekly:status", "pack_id": "pack-1"})(),
    )
    assert cli.main() == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["status"] == "READY_FOR_REVIEW"


def test_cli_weekly_return_to_safe_mode_outputs_report(session, monkeypatch, capsys) -> None:
    class StubService:
        def return_to_safe_mode(self, *, actor, correlation_id):
            return {
                "operation_mode": "pilot",
                "banner_message": "MODE PILOTE",
                "global_kill_switch": {"before": False, "after": True},
                "channels": [{"channel": "oling", "feature_enabled": False}],
                "drafts_preserved": True,
            }

    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(cli, "_build_studio_admin_service", lambda session: StubService())
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "weekly:return-to-safe-mode"})(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["global_kill_switch"]["after"] is True
    assert payload["drafts_preserved"] is True
