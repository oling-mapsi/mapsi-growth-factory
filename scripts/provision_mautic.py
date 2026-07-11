from __future__ import annotations

import json

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.core.db import Base, SessionLocal, engine
from app.infrastructure.connectors.mautic import MauticConnector, build_mautic_config
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository


def main() -> int:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        service = MauticContactSyncService(
            connector=MauticConnector(build_mautic_config()),
            repository=MauticSyncRepository(session),
            segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
        )
        print(json.dumps(service.provision(dry_run=False), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
