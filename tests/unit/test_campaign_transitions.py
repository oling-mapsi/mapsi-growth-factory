import pytest

from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, SourceEvidence
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
        [ContentAsset(campaign_run_id=campaign.id, channel="linkedin", title="t", body="b")],
    )
    campaign.source_evidences.append(
        SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1")
    )
    campaign.approve("ok", "approver@mapsi.fr")
    first = type("PublicationStub", (), {"channel": "linkedin"})()
    second = type("PublicationStub", (), {"channel": "oling"})()
    campaign.publish(first)
    campaign.publish(second)

    assert campaign.status.value == "PUBLISHED"
    assert len(campaign.publications) == 2
