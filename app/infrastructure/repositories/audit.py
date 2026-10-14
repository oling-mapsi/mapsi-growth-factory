import json

from sqlalchemy.orm import Session

from app.application.ports.audit import AuditLogPort
from app.core.security import sha256_hexdigest
from app.infrastructure.db.models import AuditLogModel


class SqlAlchemyAuditLogRepository(AuditLogPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        aggregate_id: str | None,
        event_type: str,
        payload: dict,
        *,
        asset_id: str = "",
        actor_id: str = "",
        actor_source: str = "system",
        actor_roles: list[str] | None = None,
        correlation_id: str = "",
        idempotency_key: str = "",
        previous_state: dict | None = None,
        new_state: dict | None = None,
        channel: str = "",
        result: str = "",
        source_ip: str = "",
    ) -> None:
        sanitized_payload = self._sanitize(payload)
        sanitized_previous_state = self._sanitize(previous_state or {})
        sanitized_new_state = self._sanitize(new_state or {})
        previous_integrity_hash = self._last_integrity_hash()
        model = AuditLogModel(
            campaign_run_id=aggregate_id or None,
            content_asset_id=asset_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_source=actor_source,
            actor_roles=actor_roles or [],
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            channel=channel,
            result=result,
            source_ip=source_ip,
            previous_state=sanitized_previous_state,
            new_state=sanitized_new_state,
            payload=sanitized_payload,
            previous_integrity_hash=previous_integrity_hash,
        )
        model.integrity_hash = self._compute_integrity_hash(model)
        self.session.add(model)
        self.session.commit()

    def list_events(
        self,
        *,
        campaign_id: str | None = None,
        event_type: str | None = None,
        asset_id: str | None = None,
        actor_id: str | None = None,
        channel: str | None = None,
        result: str | None = None,
        period_from=None,
        period_to=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogModel]:
        query = self.session.query(AuditLogModel)
        if campaign_id:
            query = query.filter(AuditLogModel.campaign_run_id == campaign_id)
        if event_type:
            query = query.filter(AuditLogModel.event_type == event_type)
        if asset_id:
            query = query.filter(AuditLogModel.content_asset_id == asset_id)
        if actor_id:
            query = query.filter(AuditLogModel.actor_id == actor_id)
        if channel:
            query = query.filter(AuditLogModel.channel == channel)
        if result:
            query = query.filter(AuditLogModel.result == result)
        if period_from is not None:
            query = query.filter(AuditLogModel.created_at >= period_from)
        if period_to is not None:
            query = query.filter(AuditLogModel.created_at <= period_to)
        return query.order_by(AuditLogModel.created_at.desc()).offset(offset).limit(limit).all()

    def latest_event_for_campaign(self, campaign_id: str) -> AuditLogModel | None:
        return (
            self.session.query(AuditLogModel)
            .filter(AuditLogModel.campaign_run_id == campaign_id)
            .order_by(AuditLogModel.created_at.desc())
            .first()
        )

    def verify_integrity(self, events: list[AuditLogModel] | None = None) -> bool:
        rows = events or self.session.query(AuditLogModel).order_by(AuditLogModel.created_at.asc(), AuditLogModel.id.asc()).all()
        previous_hash = ""
        for item in rows:
            if item.previous_integrity_hash != previous_hash:
                return False
            if item.integrity_hash != self._compute_integrity_hash(item):
                return False
            previous_hash = item.integrity_hash
        return True

    def _last_integrity_hash(self) -> str:
        latest = self.session.query(AuditLogModel).order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc()).first()
        return latest.integrity_hash if latest is not None else ""

    def _compute_integrity_hash(self, model: AuditLogModel) -> str:
        payload = {
            "campaign_run_id": model.campaign_run_id or "",
            "content_asset_id": model.content_asset_id,
            "event_type": model.event_type,
            "actor_id": model.actor_id,
            "actor_source": model.actor_source,
            "actor_roles": list(model.actor_roles or []),
            "correlation_id": model.correlation_id,
            "idempotency_key": model.idempotency_key,
            "channel": model.channel,
            "result": model.result,
            "source_ip": model.source_ip,
            "previous_state": dict(model.previous_state or {}),
            "new_state": dict(model.new_state or {}),
            "payload": dict(model.payload or {}),
            "previous_integrity_hash": model.previous_integrity_hash,
        }
        return sha256_hexdigest(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))

    def _sanitize(self, value):
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ("token", "secret", "password", "authorization", "cookie")):
                    continue
                if lowered in {"content_html", "content_text", "body", "email_html", "email_text", "prompt", "system_prompt"}:
                    continue
                cleaned[str(key)] = self._sanitize(item)
            return cleaned
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value
