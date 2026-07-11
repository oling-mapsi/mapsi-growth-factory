from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.ports.product_intelligence import (
    ProductChangeRepositoryPort,
    RepositoryCursorRepositoryPort,
    RepositorySourceRepositoryPort,
    SourceEvidenceRepositoryPort,
    WebhookDeliveryRepositoryPort,
)
from app.domain.entities import ProductChange, RepositoryCursor, RepositorySource, SourceEvidence, WebhookDelivery
from app.infrastructure.db.models import (
    ProductChangeModel,
    RepositoryCursorModel,
    RepositorySourceModel,
    SourceEvidenceModel,
    WebhookDeliveryModel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SqlAlchemyRepositorySourceRepository(RepositorySourceRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, full_name: str, installation_id: str, default_branch: str) -> RepositorySource:
        model = self.session.query(RepositorySourceModel).filter(RepositorySourceModel.full_name == full_name).one_or_none()
        if model is None:
            model = RepositorySourceModel(
                full_name=full_name,
                installation_id=installation_id,
                default_branch=default_branch,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
        return RepositorySource(
            id=model.id,
            full_name=model.full_name,
            installation_id=model.installation_id,
            default_branch=model.default_branch,
            created_at=model.created_at,
        )

    def list_all(self) -> list[RepositorySource]:
        models = self.session.query(RepositorySourceModel).all()
        return [
            RepositorySource(
                id=model.id,
                full_name=model.full_name,
                installation_id=model.installation_id,
                default_branch=model.default_branch,
                created_at=model.created_at,
            )
            for model in models
        ]


class SqlAlchemyRepositoryCursorRepository(RepositoryCursorRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, source_id: str, cursor_type: str, last_seen_sha: str, last_delivery_id: str) -> RepositoryCursor:
        model = (
            self.session.query(RepositoryCursorModel)
            .filter(
                RepositoryCursorModel.repository_source_id == source_id,
                RepositoryCursorModel.cursor_type == cursor_type,
            )
            .one_or_none()
        )
        if model is None:
            model = RepositoryCursorModel(
                repository_source_id=source_id,
                cursor_type=cursor_type,
                last_seen_sha=last_seen_sha,
                last_delivery_id=last_delivery_id,
                last_polled_at=utcnow(),
            )
            self.session.add(model)
        else:
            model.last_seen_sha = last_seen_sha
            model.last_delivery_id = last_delivery_id
            model.last_polled_at = utcnow()
        self.session.commit()
        return RepositoryCursor(
            id=model.id,
            repository_source_id=model.repository_source_id,
            cursor_type=model.cursor_type,
            last_seen_sha=model.last_seen_sha,
            last_delivery_id=model.last_delivery_id,
            last_polled_at=model.last_polled_at,
        )

    def get(self, source_id: str, cursor_type: str) -> RepositoryCursor | None:
        model = (
            self.session.query(RepositoryCursorModel)
            .filter(
                RepositoryCursorModel.repository_source_id == source_id,
                RepositoryCursorModel.cursor_type == cursor_type,
            )
            .one_or_none()
        )
        if model is None:
            return None
        return RepositoryCursor(
            id=model.id,
            repository_source_id=model.repository_source_id,
            cursor_type=model.cursor_type,
            last_seen_sha=model.last_seen_sha,
            last_delivery_id=model.last_delivery_id,
            last_polled_at=model.last_polled_at,
        )


class SqlAlchemyProductChangeRepository(ProductChangeRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_many(self, changes: list[ProductChange]) -> list[ProductChange]:
        persisted: list[ProductChange] = []
        for change in changes:
            model = ProductChangeModel(
                id=change.id,
                repository_source_id=change.repository_source_id,
                repository_full_name=change.repository_full_name,
                sha=change.sha,
                pr_number=change.pr_number,
                issue_numbers=change.issue_numbers,
                release_tag=change.release_tag,
                deployment_ref=change.deployment_ref,
                production_status=change.production_status,
                change_note_path=change.change_note_path,
                eligible_for_communication=change.eligible_for_communication,
                confidential=change.confidential,
                target_client_key=change.target_client_key,
                capability_key=change.capability_key,
                summary=change.summary,
                contract_version=change.contract_version,
                deployment_proven=change.deployment_proven,
                collected_at=change.collected_at,
                raw_payload=change.raw_payload,
            )
            self.session.merge(model)
            persisted.append(change)
        self.session.commit()
        return persisted


class SqlAlchemySourceEvidenceRepository(SourceEvidenceRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_many(self, evidences: list[SourceEvidence]) -> list[SourceEvidence]:
        for evidence in evidences:
            self.session.merge(
                SourceEvidenceModel(
                    id=evidence.id,
                    campaign_run_id=evidence.campaign_run_id,
                    product_change_id=evidence.product_change_id or None,
                    source_system=evidence.source_system,
                    evidence_type=evidence.evidence_type,
                    reference=evidence.reference,
                    payload=evidence.payload,
                    created_at=evidence.created_at,
                )
            )
        self.session.commit()
        return evidences


class SqlAlchemyWebhookDeliveryRepository(WebhookDeliveryRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_if_absent(self, delivery: WebhookDelivery) -> tuple[WebhookDelivery, bool]:
        model = WebhookDeliveryModel(
            delivery_id=delivery.delivery_id,
            event_type=delivery.event_type,
            repository_full_name=delivery.repository_full_name,
            signature_valid=delivery.signature_valid,
            processed=delivery.processed,
            status=delivery.status,
            payload=delivery.payload,
            received_at=delivery.received_at,
        )
        self.session.add(model)
        try:
            self.session.commit()
            return delivery, True
        except IntegrityError:
            self.session.rollback()
            existing = self.session.query(WebhookDeliveryModel).filter(WebhookDeliveryModel.delivery_id == delivery.delivery_id).one()
            return (
                WebhookDelivery(
                    id=existing.id,
                    delivery_id=existing.delivery_id,
                    event_type=existing.event_type,
                    repository_full_name=existing.repository_full_name,
                    signature_valid=existing.signature_valid,
                    processed=existing.processed,
                    status=existing.status,
                    payload=existing.payload,
                    received_at=existing.received_at,
                ),
                False,
            )

    def mark(self, delivery_id: str, status: str, processed: bool, signature_valid: bool) -> None:
        model = self.session.query(WebhookDeliveryModel).filter(WebhookDeliveryModel.delivery_id == delivery_id).one()
        model.processed = processed
        model.status = status
        model.signature_valid = signature_valid
        self.session.commit()
