import pytest

from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, Publication, SourceEvidence
from app.domain.errors import ApprovalPrerequisiteError, CampaignPublicationForbiddenError, InvalidStateTransitionError


def test_approve_requires_assets_and_evidence() -> None:
    campaign = CampaignRun(name="A", objective="B")
    with pytest.raises(ApprovalPrerequisiteError):
        campaign.approve("ok", "approver@mapsi.fr")


def test_request_changes_is_invalid_from_draft() -> None:
    campaign = CampaignRun(name="A", objective="B")
    with pytest.raises(InvalidStateTransitionError):
        campaign.request_changes("needs work", "approver@mapsi.fr")


def test_publish_requires_approved_or_published_state() -> None:
    campaign = CampaignRun(name="A", objective="B")
    with pytest.raises(CampaignPublicationForbiddenError):
        campaign.publish(
            publication=type("PublicationStub", (), {"channel": "linkedin"})()
        )


def test_second_channel_can_be_published_after_first_one() -> None:
    campaign = CampaignRun(name="A", objective="B")
    campaign.mark_generated(
        EditorialBrief(campaign_run_id=campaign.id, title="t", summary="s"),
        [
            ContentAsset(campaign_run_id=campaign.id, channel="linkedin", title="t", body="b"),
            ContentAsset(campaign_run_id=campaign.id, channel="oling", title="t2", body="b2"),
        ],
    )
    campaign.source_evidences.append(
        SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1")
    )
    campaign.approve("ok", "approver@mapsi.fr")
    first = Publication(campaign_run_id=campaign.id, content_asset_id=campaign.content_assets[0].id, channel="linkedin", external_reference="linkedin:1")
    second = Publication(campaign_run_id=campaign.id, content_asset_id=campaign.content_assets[1].id, channel="oling", external_reference="oling:1")
    campaign.publish(first)
    campaign.publish(second)

    assert campaign.status.value == "PUBLISHED"
    assert len(campaign.publications) == 2


def test_campaign_can_be_partially_published() -> None:
    campaign = CampaignRun(name="A", objective="B")
    campaign.mark_generated(
        EditorialBrief(campaign_run_id=campaign.id, title="t", summary="s"),
        [
            ContentAsset(campaign_run_id=campaign.id, channel="linkedin", title="t", body="b"),
            ContentAsset(campaign_run_id=campaign.id, channel="oling", title="t2", body="b2"),
        ],
    )
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    campaign.approve("ok", "approver@mapsi.fr")

    first_asset = campaign.content_assets[0]
    second_asset = campaign.content_assets[1]
    campaign.publish(Publication(campaign_run_id=campaign.id, content_asset_id=first_asset.id, channel="linkedin", external_reference="li:1"))

    assert campaign.status.value == "PARTIALLY_PUBLISHED"
    assert first_asset.status.value == "PUBLISHED"
    assert second_asset.status.value == "APPROVED"
