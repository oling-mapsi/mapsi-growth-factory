from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.tasks import InMemoryTaskQueue


def main() -> int:
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        service = GitHubIntelligenceService(
            connector=GitHubConnector(settings),
            repository_sources=SqlAlchemyRepositorySourceRepository(session),
            repository_cursors=SqlAlchemyRepositoryCursorRepository(session),
            product_changes=SqlAlchemyProductChangeRepository(session),
            source_evidences=SqlAlchemySourceEvidenceRepository(session),
            webhook_deliveries=SqlAlchemyWebhookDeliveryRepository(session),
            task_queue=InMemoryTaskQueue(),
        )
        processed = service.run_weekly_backfill()
        print(f"Processed {processed} GitHub product changes during weekly backfill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
