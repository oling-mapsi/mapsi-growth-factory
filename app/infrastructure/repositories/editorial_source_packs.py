from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.domain.entities import EditorialSourceAttachmentReference, EditorialSourceItem, EditorialSourcePack
from app.infrastructure.db.models import (
    EditorialSourceAttachmentReferenceModel,
    EditorialSourceItemModel,
    EditorialSourcePackModel,
)


class EditorialSourcePackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, pack: EditorialSourcePack) -> EditorialSourcePack:
        model = self._to_model(pack)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self.get(pack.id) or pack

    def get(self, pack_id: str) -> EditorialSourcePack | None:
        model = (
            self.session.query(EditorialSourcePackModel)
            .options(
                selectinload(EditorialSourcePackModel.items).selectinload(EditorialSourceItemModel.attachments),
            )
            .filter(EditorialSourcePackModel.id == pack_id)
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def save(self, pack: EditorialSourcePack) -> EditorialSourcePack:
        model = self.session.get(EditorialSourcePackModel, pack.id)
        if model is None:
            return self.add(pack)
        replacement = self._to_model(pack)
        self.session.merge(replacement)
        self.session.commit()
        return self.get(pack.id) or pack

    def list_validated(self, *, campaign_type: str, weekly_pack_id: str = "") -> list[EditorialSourcePack]:
        query = (
            self.session.query(EditorialSourcePackModel)
            .options(
                selectinload(EditorialSourcePackModel.items).selectinload(EditorialSourceItemModel.attachments),
            )
            .filter(EditorialSourcePackModel.campaign_type == campaign_type)
            .filter(EditorialSourcePackModel.status == "VALIDATED")
        )
        if weekly_pack_id:
            query = query.filter(EditorialSourcePackModel.weekly_pack_id == weekly_pack_id)
        return [self._to_entity(model) for model in query.order_by(EditorialSourcePackModel.created_at.desc()).all()]

    def delete_item(self, pack_id: str, item_id: str) -> EditorialSourcePack | None:
        model = self.session.get(EditorialSourceItemModel, item_id)
        if model is None or model.source_pack_id != pack_id:
            return self.get(pack_id)
        self.session.delete(model)
        self.session.commit()
        return self.get(pack_id)

    def _to_model(self, pack: EditorialSourcePack) -> EditorialSourcePackModel:
        return EditorialSourcePackModel(
            id=pack.id,
            weekly_pack_id=pack.weekly_pack_id,
            campaign_type=pack.campaign_type,
            title=pack.title,
            summary=pack.summary,
            status=pack.status,
            confidentiality_level=pack.confidentiality_level,
            created_by=pack.created_by,
            created_at=pack.created_at,
            validated_by=pack.validated_by,
            validated_at=pack.validated_at,
            items=[
                EditorialSourceItemModel(
                    id=item.id,
                    source_pack_id=pack.id,
                    source_type=item.source_type,
                    source_reference=item.source_reference,
                    source_title=item.source_title,
                    source_date=item.source_date,
                    source_author=item.source_author,
                    factual_summary=item.factual_summary,
                    usable_facts=list(item.usable_facts),
                    anonymized_facts=list(item.anonymized_facts),
                    prohibited_facts=list(item.prohibited_facts),
                    client_name=item.client_name,
                    client_name_usage_authorized=item.client_name_usage_authorized,
                    confidentiality_level=item.confidentiality_level,
                    evidence_quality=item.evidence_quality,
                    source_url=item.source_url,
                    external_source_id=item.external_source_id,
                    content_hash=item.content_hash,
                    manual_input=dict(item.manual_input),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    attachments=[
                        EditorialSourceAttachmentReferenceModel(
                            id=attachment.id,
                            source_item_id=item.id,
                            file_name=attachment.file_name,
                            media_type=attachment.media_type,
                            storage_reference=attachment.storage_reference,
                            source_url=attachment.source_url,
                            content_hash=attachment.content_hash,
                            created_at=attachment.created_at,
                        )
                        for attachment in item.attachment_references
                    ],
                )
                for item in pack.items
            ],
        )

    def _to_entity(self, model: EditorialSourcePackModel) -> EditorialSourcePack:
        return EditorialSourcePack(
            id=model.id,
            weekly_pack_id=model.weekly_pack_id,
            campaign_type=model.campaign_type,
            title=model.title,
            summary=model.summary,
            status=model.status,
            confidentiality_level=model.confidentiality_level,
            created_by=model.created_by,
            created_at=model.created_at,
            validated_by=model.validated_by,
            validated_at=model.validated_at,
            items=[
                EditorialSourceItem(
                    id=item.id,
                    source_pack_id=item.source_pack_id,
                    source_type=item.source_type,
                    source_reference=item.source_reference,
                    source_title=item.source_title,
                    source_date=item.source_date,
                    source_author=item.source_author,
                    factual_summary=item.factual_summary,
                    usable_facts=list(item.usable_facts or []),
                    anonymized_facts=list(item.anonymized_facts or []),
                    prohibited_facts=list(item.prohibited_facts or []),
                    client_name=item.client_name,
                    client_name_usage_authorized=item.client_name_usage_authorized,
                    confidentiality_level=item.confidentiality_level,
                    evidence_quality=item.evidence_quality,
                    source_url=item.source_url,
                    external_source_id=item.external_source_id,
                    content_hash=item.content_hash,
                    manual_input=dict(item.manual_input or {}),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    attachment_references=[
                        EditorialSourceAttachmentReference(
                            id=attachment.id,
                            source_item_id=attachment.source_item_id,
                            file_name=attachment.file_name,
                            media_type=attachment.media_type,
                            storage_reference=attachment.storage_reference,
                            source_url=attachment.source_url,
                            content_hash=attachment.content_hash,
                            created_at=attachment.created_at,
                        )
                        for attachment in item.attachments
                    ],
                )
                for item in model.items
            ],
        )
