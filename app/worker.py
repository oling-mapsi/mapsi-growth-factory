import logging
import time

from app.application.services.task_worker_service import TaskWorkerService
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.tasks import RedisTaskQueue
from app.application.services.github_intelligence_service import GitHubIntelligenceService

logger = logging.getLogger(__name__)


def run_worker(poll_timeout: int = 5, max_jobs: int | None = None) -> int:
    settings = get_settings()
    queue = RedisTaskQueue(settings.redis_url, settings.redis_queue_name)
    processed = 0
    while True:
        job = queue.dequeue(timeout=poll_timeout)
        if job is None:
            if max_jobs is not None:
                return processed
            time.sleep(0.2)
            continue
        with SessionLocal() as session:
            github_intelligence = GitHubIntelligenceService(
                connector=GitHubConnector(settings),
                repository_sources=SqlAlchemyRepositorySourceRepository(session),
                repository_cursors=SqlAlchemyRepositoryCursorRepository(session),
                product_changes=SqlAlchemyProductChangeRepository(session),
                source_evidences=SqlAlchemySourceEvidenceRepository(session),
                webhook_deliveries=SqlAlchemyWebhookDeliveryRepository(session),
                task_queue=queue,
            )
            service = TaskWorkerService(
                repository=SqlAlchemyCampaignRepository(session),
                audit_log=SqlAlchemyAuditLogRepository(session),
                github_intelligence=github_intelligence,
            )
            service.handle(job)
        processed += 1
        logger.info("Processed job %s", job["id"])
        if max_jobs is not None and processed >= max_jobs:
            return processed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
