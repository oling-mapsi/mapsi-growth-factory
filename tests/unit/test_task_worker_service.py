from app.application.services.task_worker_service import TaskWorkerService
from app.domain.entities import CampaignRun
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


def test_worker_refreshes_publication_metrics(session) -> None:
    campaign_repo = SqlAlchemyCampaignRepository(session)
    audit_repo = SqlAlchemyAuditLogRepository(session)
    campaign = CampaignRun(name="Worker", objective="Metrics")
    campaign_repo.add(campaign)

    worker = TaskWorkerService(campaign_repo, audit_repo)
    worker.handle(
        {
            "id": "job-1",
            "task_name": "campaign.refresh_publication_metrics",
            "payload": {"campaign_id": campaign.id, "channels": ["linkedin", "oling"]},
        }
    )

    refreshed = campaign_repo.get(campaign.id)
    assert refreshed is not None
    assert len(refreshed.interactions) == 2
    assert refreshed.interactions[0].interaction_type == "publication_metrics_refreshed"
