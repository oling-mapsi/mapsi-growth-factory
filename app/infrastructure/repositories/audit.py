from sqlalchemy.orm import Session

from app.application.ports.audit import AuditLogPort
from app.infrastructure.db.models import AuditLogModel


class SqlAlchemyAuditLogRepository(AuditLogPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, aggregate_id: str, event_type: str, payload: dict) -> None:
        self.session.add(
            AuditLogModel(
                campaign_run_id=aggregate_id,
                event_type=event_type,
                payload=payload,
            )
        )
        self.session.commit()
