from datetime import UTC, datetime

from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset, EditorialBrief, Publication, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.db.models import CampaignRunModel, ContentAssetModel
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


def test_sqlalchemy_repository_persists_nested_aggregates(session) -> None:
    repository = SqlAlchemyCampaignRepository(session)
    campaign = CampaignRun(name="Repo", objective="Persistence", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(
        AudienceSegment(campaign_run_id=campaign.id, name="CTO", description="Tech leaders")
    )
    campaign.editorial_briefs.append(
        EditorialBrief(campaign_run_id=campaign.id, title="Brief", summary="Summary")
    )
    campaign.content_assets.append(
        ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="linkedin_post",
            channel="linkedin",
            title="Post",
            body="Copy",
            status=AssetStatus.APPROVED,
            revision=2,
        )
    )
    campaign.source_evidences.append(
        SourceEvidence(campaign_run_id=campaign.id, source_system="github", reference="github:123")
    )
    campaign.publications.append(
        Publication(campaign_run_id=campaign.id, channel="linkedin", external_reference="linkedin:123")
    )

    repository.add(campaign)
    persisted = repository.get(campaign.id)

    assert persisted is not None
    assert persisted.content_assets[0].channel == "linkedin"
    assert persisted.content_assets[0].status.value == "APPROVED"
    assert persisted.content_assets[0].revision == 2
    assert persisted.content_assets[0].content_version == 2
    assert persisted.content_assets[0].content_html == "Copy"
    assert persisted.content_assets[0].content_text == "Copy"
    assert persisted.publications[0].external_reference == "linkedin:123"


def test_repository_backfills_historical_asset_columns(session) -> None:
    now = datetime.now(UTC)
    campaign = CampaignRunModel(
        id="legacy-campaign",
        name="Legacy",
        objective="History",
        status=CampaignStatus.APPROVED.value,
        created_at=now,
        updated_at=now,
    )
    session.add(campaign)
    session.add(
        ContentAssetModel(
            id="legacy-asset",
            campaign_run_id="legacy-campaign",
            asset_type="linkedin_company_post",
            channel="linkedin",
            locale="fr-FR",
            title="Legacy title",
            subject="",
            body="<p>Legacy body</p>",
            content_html="",
            content_text="",
            excerpt="",
            call_to_action="",
            target_url="",
            evidence_ids=["e1"],
            source_evidence_ids=[],
            audience_segment_id="seg-1",
            status=AssetStatus.APPROVED.value,
            content_version=1,
            content_hash="legacy-hash",
            approved_content_hash="",
            approved_by="admin",
            approved_at=now,
            scheduled_at=None,
            published_at=None,
            external_publication_id="",
            external_publication_url="",
            last_error="",
            retry_count=0,
            results={},
            revision=3,
            created_at=now,
        )
    )
    session.commit()

    persisted = SqlAlchemyCampaignRepository(session).get("legacy-campaign")

    assert persisted is not None
    asset = persisted.content_assets[0]
    assert asset.content_html == "<p>Legacy body</p>"
    assert asset.content_text == "Legacy body"
    assert asset.source_evidence_ids == ["e1"]
    assert asset.content_version == 3
    assert asset.approved_content_hash == ""
