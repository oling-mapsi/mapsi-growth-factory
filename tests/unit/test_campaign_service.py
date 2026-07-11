import pytest

from app.application.dto import CreateCampaignCommand, PublishCampaignCommand, ReviewCampaignCommand
from app.application.services.campaign_service import CampaignService
from app.domain.errors import CampaignPublicationForbiddenError
from app.infrastructure.connectors.fakes import (
    CompositeSimulatedGenerator,
    CompositeSimulatedPublisher,
    SimulatedDolibarrConnector,
    SimulatedGitHubConnector,
    SimulatedLinkedInConnector,
    SimulatedMAPSIConnector,
    SimulatedMauticConnector,
    SimulatedMicrosoftGraphConnector,
    SimulatedOlingSiteConnector,
)
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.tasks import InMemoryTaskQueue


def build_service(session) -> CampaignService:
    return CampaignService(
        repository=SqlAlchemyCampaignRepository(session),
        generator=CompositeSimulatedGenerator(
            [
                SimulatedGitHubConnector(),
                SimulatedMAPSIConnector(),
                SimulatedMicrosoftGraphConnector(),
                SimulatedMauticConnector(),
                SimulatedDolibarrConnector(),
            ]
        ),
        publisher=CompositeSimulatedPublisher(
            {
                "linkedin": SimulatedLinkedInConnector(),
                "oling": SimulatedOlingSiteConnector(),
            }
        ),
        audit_log=SqlAlchemyAuditLogRepository(session),
        task_queue=InMemoryTaskQueue(),
    )


def test_campaign_lifecycle_requires_approval_before_publish(session) -> None:
    service = build_service(session)
    campaign = service.create_campaign(
        CreateCampaignCommand(
            name="Launch Q3",
            objective="Generate qualified leads",
            audience_name="DSI",
            audience_description="Enterprise decision makers",
        )
    )
    campaign = service.generate_campaign(campaign.id)
    with pytest.raises(CampaignPublicationForbiddenError):
        service.publish(campaign.id, PublishCampaignCommand(channels=["linkedin"]))

    campaign = service.approve(
        campaign.id,
        ReviewCampaignCommand(decided_by="reviewer@mapsi.fr", comment="Ready"),
    )
    campaign = service.publish(campaign.id, PublishCampaignCommand(channels=["linkedin", "oling"]))

    assert campaign.status.value == "PUBLISHED"
    assert len(campaign.publications) == 2


def test_request_changes_moves_campaign_back_to_review(session) -> None:
    service = build_service(session)
    campaign = service.create_campaign(
        CreateCampaignCommand(
            name="Launch Q4",
            objective="Increase traffic",
            audience_name="CTO",
            audience_description="Mid-market CTOs",
        )
    )
    campaign = service.generate_campaign(campaign.id)
    campaign = service.request_changes(
        campaign.id,
        ReviewCampaignCommand(decided_by="reviewer@mapsi.fr", comment="Need stronger CTA"),
    )

    assert campaign.status.value == "CHANGES_REQUESTED"
    assert campaign.approval_decisions[-1].comment == "Need stronger CTA"
