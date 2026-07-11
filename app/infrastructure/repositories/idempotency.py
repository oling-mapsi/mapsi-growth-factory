from sqlalchemy.orm import Session

from app.application.ports.idempotency import IdempotencyStorePort
from app.infrastructure.db.models import IdempotencyKeyModel


class SqlAlchemyIdempotencyRepository(IdempotencyStorePort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, method: str, path: str, key: str) -> dict | None:
        record = (
            self.session.query(IdempotencyKeyModel)
            .filter(
                IdempotencyKeyModel.method == method,
                IdempotencyKeyModel.path == path,
                IdempotencyKeyModel.idempotency_key == key,
            )
            .one_or_none()
        )
        if record is None:
            return None
        return {
            "request_fingerprint": record.request_fingerprint,
            "response_status": record.response_status,
            "response_body": record.response_body,
        }

    def save(
        self,
        method: str,
        path: str,
        key: str,
        request_fingerprint: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        self.session.add(
            IdempotencyKeyModel(
                method=method,
                path=path,
                idempotency_key=key,
                request_fingerprint=request_fingerprint,
                response_status=response_status,
                response_body=response_body,
            )
        )
        self.session.commit()
