from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.infrastructure.db.models import ChannelOperationalAuditModel, ChannelOperationalStateModel, GlobalOperationalStateModel


@dataclass
class ChannelOperationalRecord:
    channel: str
    feature_enabled: bool
    feature_expires_at: datetime | None
    emergency_kill_switch: bool
    last_health_check: datetime | None
    last_error: str
    updated_by: str
    updated_at: datetime | None


@dataclass
class GlobalOperationalRecord:
    global_kill_switch: bool
    updated_by: str
    updated_at: datetime | None


class ChannelOperationalStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_channel(self, channel: str) -> ChannelOperationalRecord | None:
        model = self.session.query(ChannelOperationalStateModel).filter(ChannelOperationalStateModel.channel == channel).one_or_none()
        if model is None:
            return None
        feature_expires_at = self._utc(model.feature_expires_at)
        if feature_expires_at is not None and feature_expires_at <= datetime.now(UTC):
            model.feature_enabled = False
            model.feature_expires_at = None
            model.updated_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(model)
        return self._to_channel(model)

    def list_channels(self) -> list[ChannelOperationalRecord]:
        models = self.session.query(ChannelOperationalStateModel).order_by(ChannelOperationalStateModel.channel.asc()).all()
        return [self._to_channel(model) for model in models]

    def save_channel(
        self,
        *,
        channel: str,
        feature_enabled: bool,
        emergency_kill_switch: bool,
        updated_by: str,
        feature_expires_at: datetime | None = None,
        last_health_check: datetime | None = None,
        last_error: str | None = None,
    ) -> ChannelOperationalRecord:
        model = self.session.query(ChannelOperationalStateModel).filter(ChannelOperationalStateModel.channel == channel).one_or_none()
        if model is None:
            model = ChannelOperationalStateModel(channel=channel)
            self.session.add(model)
        model.feature_enabled = feature_enabled
        model.feature_expires_at = feature_expires_at
        model.emergency_kill_switch = emergency_kill_switch
        if last_health_check is not None:
            model.last_health_check = last_health_check
        if last_error is not None:
            model.last_error = last_error
        model.updated_by = updated_by
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)
        return self._to_channel(model)

    def update_health_check(self, *, channel: str, last_error: str) -> ChannelOperationalRecord:
        current = self.get_channel(channel)
        return self.save_channel(
            channel=channel,
            feature_enabled=current.feature_enabled if current is not None else False,
            feature_expires_at=current.feature_expires_at if current is not None else None,
            emergency_kill_switch=current.emergency_kill_switch if current is not None else False,
            updated_by=current.updated_by if current is not None else "system",
            last_health_check=datetime.now(UTC),
            last_error=last_error,
        )

    def get_global(self) -> GlobalOperationalRecord | None:
        model = self.session.query(GlobalOperationalStateModel).order_by(GlobalOperationalStateModel.updated_at.desc()).first()
        return self._to_global(model) if model is not None else None

    def save_global(self, *, global_kill_switch: bool, updated_by: str) -> GlobalOperationalRecord:
        model = self.session.query(GlobalOperationalStateModel).order_by(GlobalOperationalStateModel.updated_at.desc()).first()
        if model is None:
            model = GlobalOperationalStateModel()
            self.session.add(model)
        model.global_kill_switch = global_kill_switch
        model.updated_by = updated_by
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)
        return self._to_global(model)

    def append_audit(
        self,
        *,
        scope: str,
        action: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload: dict,
    ) -> None:
        self.session.add(
            ChannelOperationalAuditModel(
                scope=scope,
                action=action,
                actor_id=actor_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        self.session.commit()

    def is_global_kill_switch_active(self, *, static_default: bool) -> bool:
        record = self.get_global()
        if record is None:
            return static_default
        return record.global_kill_switch

    def is_channel_feature_enabled(self, *, channel: str, static_default: bool, safe_default_enabled: bool) -> bool:
        record = self.get_channel(channel)
        if record is None:
            return False if safe_default_enabled else static_default
        return record.feature_enabled

    def is_channel_kill_switch_active(self, channel: str) -> bool:
        record = self.get_channel(channel)
        return record.emergency_kill_switch if record is not None else False

    def _to_channel(self, model: ChannelOperationalStateModel) -> ChannelOperationalRecord:
        return ChannelOperationalRecord(
            channel=model.channel,
            feature_enabled=model.feature_enabled,
            feature_expires_at=self._utc(model.feature_expires_at),
            emergency_kill_switch=model.emergency_kill_switch,
            last_health_check=self._utc(model.last_health_check),
            last_error=model.last_error,
            updated_by=model.updated_by,
            updated_at=self._utc(model.updated_at),
        )

    def _to_global(self, model: GlobalOperationalStateModel) -> GlobalOperationalRecord:
        return GlobalOperationalRecord(
            global_kill_switch=model.global_kill_switch,
            updated_by=model.updated_by,
            updated_at=self._utc(model.updated_at),
        )

    def _utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
