from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.entities import WeeklyCommunicationPack
from app.infrastructure.db.models import WeeklyCommunicationPackModel


class WeeklyCommunicationPackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, pack: WeeklyCommunicationPack) -> WeeklyCommunicationPack:
        model = self._to_model(pack)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def get(self, pack_id: str) -> WeeklyCommunicationPack | None:
        model = self.session.get(WeeklyCommunicationPackModel, pack_id)
        return self._to_entity(model) if model else None

    def get_by_week(self, *, year: int, week_number: int) -> WeeklyCommunicationPack | None:
        model = (
            self.session.query(WeeklyCommunicationPackModel)
            .filter(WeeklyCommunicationPackModel.year == year, WeeklyCommunicationPackModel.week_number == week_number)
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def list(self) -> list[WeeklyCommunicationPack]:
        models = self.session.query(WeeklyCommunicationPackModel).order_by(WeeklyCommunicationPackModel.created_at.desc()).all()
        return [self._to_entity(model) for model in models]

    def save(self, pack: WeeklyCommunicationPack) -> WeeklyCommunicationPack:
        model = self.session.get(WeeklyCommunicationPackModel, pack.id)
        if model is None:
            return self.add(pack)
        replacement = self._to_model(pack)
        self.session.merge(replacement)
        self.session.commit()
        persisted = self.session.get(WeeklyCommunicationPackModel, pack.id)
        return self._to_entity(persisted)

    def _to_model(self, pack: WeeklyCommunicationPack) -> WeeklyCommunicationPackModel:
        return WeeklyCommunicationPackModel(
            id=pack.id,
            week_reference=pack.week_reference,
            year=pack.year,
            week_number=pack.week_number,
            status=pack.status,
            created_at=pack.created_at,
            generated_at=pack.generated_at,
            reviewed_at=pack.reviewed_at,
            completed_at=pack.completed_at,
            campaign_ids=list(pack.campaign_ids),
            global_summary=dict(pack.global_summary),
            operational_errors=list(pack.operational_errors),
            pilot_mode=pack.pilot_mode,
        )

    def _to_entity(self, model: WeeklyCommunicationPackModel) -> WeeklyCommunicationPack:
        return WeeklyCommunicationPack(
            id=model.id,
            week_reference=model.week_reference,
            year=model.year,
            week_number=model.week_number,
            status=model.status,
            created_at=model.created_at,
            generated_at=model.generated_at,
            reviewed_at=model.reviewed_at,
            completed_at=model.completed_at,
            campaign_ids=list(model.campaign_ids or []),
            global_summary=dict(model.global_summary or {}),
            operational_errors=list(model.operational_errors or []),
            pilot_mode=model.pilot_mode,
        )
