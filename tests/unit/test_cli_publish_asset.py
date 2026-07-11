import json

from app import cli
from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import CampaignStatus
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


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

        def publish_asset(self, campaign_id: str, asset_id: str, *, dry_run: bool = False) -> dict:
            return {"campaign_id": campaign_id, "asset_id": asset_id, "dry_run": dry_run, "channel": "oling"}

    monkeypatch.setattr(cli, "OlingNewsPublisher", StubPublisher)
    monkeypatch.setattr(cli, "build_oling_config", lambda: object())
    monkeypatch.setattr(cli, "OlingConnector", lambda config: object())
    monkeypatch.setattr(cli, "engine", object())
    monkeypatch.setattr(cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {"command": "publish-asset", "asset_id": asset.id, "channel": "oling", "dry_run": True})(),
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["asset_id"] == asset.id
