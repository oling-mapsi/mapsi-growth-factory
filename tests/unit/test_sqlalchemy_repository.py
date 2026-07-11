from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset, EditorialBrief, Publication, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
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
    assert persisted.publications[0].external_reference == "linkedin:123"
