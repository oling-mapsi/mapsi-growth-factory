from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.db.models import StudioAdminAccessAuditModel, StudioAdminJtiModel


class StudioAdminJtiRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def exists(self, jti: str) -> bool:
        return self.session.query(StudioAdminJtiModel).filter(StudioAdminJtiModel.jti == jti).one_or_none() is not None

    def register(self, *, jti: str, issuer: str, audience: str, subject: str, expires_at, key_id: str) -> None:
        try:
            self.session.add(
                StudioAdminJtiModel(
                    jti=jti,
                    issuer=issuer,
                    audience=audience,
                    subject=subject,
                    expires_at=expires_at,
                    key_id=key_id,
                )
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise


class StudioAdminAccessAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        actor_id: str,
        actor_roles: list[str],
        actor_permissions: list[str],
        source: str,
        jti: str,
        correlation_id: str,
        source_ip: str,
        path: str,
        method: str,
    ) -> None:
        self.session.add(
            StudioAdminAccessAuditModel(
                actor_id=actor_id,
                actor_roles=actor_roles,
                actor_permissions=actor_permissions,
                source=source,
                jti=jti,
                correlation_id=correlation_id,
                source_ip=source_ip,
                path=path,
                method=method,
            )
        )
        self.session.commit()
