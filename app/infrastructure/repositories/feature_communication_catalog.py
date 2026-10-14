from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.entities import FeatureCommunicationCatalogEntry
from app.infrastructure.db.models import FeatureCommunicationCatalogModel


class FeatureCommunicationCatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_enabled(self) -> list[FeatureCommunicationCatalogEntry]:
        models = (
            self.session.query(FeatureCommunicationCatalogModel)
            .filter(FeatureCommunicationCatalogModel.enabled.is_(True))
            .order_by(FeatureCommunicationCatalogModel.communication_priority.asc(), FeatureCommunicationCatalogModel.feature_id.asc())
            .all()
        )
        return [self._to_entity(model) for model in models]

    def save(self, entry: FeatureCommunicationCatalogEntry) -> FeatureCommunicationCatalogEntry:
        model = self.session.get(FeatureCommunicationCatalogModel, entry.feature_id)
        if model is None:
            model = FeatureCommunicationCatalogModel(feature_id=entry.feature_id)
            self.session.add(model)
        self._apply(model, entry)
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def mark_communicated(self, feature_id: str, communicated_at: datetime) -> None:
        model = self.session.get(FeatureCommunicationCatalogModel, feature_id)
        if model is None:
            return
        model.last_communicated_at = communicated_at
        self.session.commit()

    def _apply(self, model: FeatureCommunicationCatalogModel, entry: FeatureCommunicationCatalogEntry) -> None:
        model.module = entry.module
        model.title = entry.title
        model.functional_description = entry.functional_description
        model.user_benefit = entry.user_benefit
        model.target_roles = list(entry.target_roles)
        model.target_modules = list(entry.target_modules)
        model.minimum_version = entry.minimum_version
        model.availability = entry.availability
        model.deep_link_template = entry.deep_link_template
        model.communication_priority = entry.communication_priority
        model.last_communicated_at = entry.last_communicated_at
        model.minimum_repeat_delay = entry.minimum_repeat_delay
        model.source_evidence_ids = list(entry.source_evidence_ids)
        model.enabled = entry.enabled

    def _to_entity(self, model: FeatureCommunicationCatalogModel) -> FeatureCommunicationCatalogEntry:
        return FeatureCommunicationCatalogEntry(
            feature_id=model.feature_id,
            module=model.module,
            title=model.title,
            functional_description=model.functional_description,
            user_benefit=model.user_benefit,
            target_roles=list(model.target_roles or []),
            target_modules=list(model.target_modules or []),
            minimum_version=model.minimum_version,
            availability=model.availability,
            deep_link_template=model.deep_link_template,
            communication_priority=model.communication_priority,
            last_communicated_at=model.last_communicated_at,
            minimum_repeat_delay=model.minimum_repeat_delay,
            source_evidence_ids=list(model.source_evidence_ids or []),
            enabled=model.enabled,
        )
