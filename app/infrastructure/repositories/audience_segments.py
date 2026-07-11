from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.domain.entities import AudienceFact, AudienceSegmentAuditEntry, AudienceSegmentPreview
from app.infrastructure.db.models import (
    AudienceSegmentAuditModel,
    AudienceSegmentPreviewModel,
    ContactMembershipModel,
    CustomerAccountModel,
    FeatureAdoptionModel,
    MapsiInstanceModel,
)


class AudienceSegmentationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_audience_facts(self) -> list[AudienceFact]:
        rows = (
            self.session.query(
                ContactMembershipModel,
                CustomerAccountModel.external_account_id,
                MapsiInstanceModel.instance_key,
                FeatureAdoptionModel.module_key,
                FeatureAdoptionModel.events_last_7_days,
            )
            .join(CustomerAccountModel, CustomerAccountModel.id == ContactMembershipModel.customer_account_id)
            .join(MapsiInstanceModel, MapsiInstanceModel.id == CustomerAccountModel.mapsi_instance_id)
            .outerjoin(FeatureAdoptionModel, FeatureAdoptionModel.contact_membership_id == ContactMembershipModel.id)
            .all()
        )
        grouped: dict[str, dict] = {}
        for membership, client_key, instance_key, module_key, module_events in rows:
            item = grouped.setdefault(
                membership.id,
                {
                    "membership": membership,
                    "client_key": client_key,
                    "instance_key": instance_key,
                    "module_events": defaultdict(int),
                },
            )
            if module_key:
                item["module_events"][module_key] = max(item["module_events"][module_key], module_events or 0)
        facts: list[AudienceFact] = []
        for item in grouped.values():
            membership = item["membership"]
            module_events = dict(item["module_events"])
            facts.append(
                AudienceFact(
                    membership_id=membership.id,
                    customer_account_id=membership.customer_account_id,
                    client_key=item["client_key"],
                    role_key=membership.role_key,
                    active=membership.active,
                    communication_eligible=membership.communication_eligible,
                    opted_out=membership.opted_out,
                    module_keys=sorted(module_events.keys()),
                    module_events=module_events,
                    instance_key=item["instance_key"],
                    created_at=membership.created_at,
                    last_activity_at=membership.last_activity_at,
                )
            )
        return facts

    def save_preview(self, preview: AudienceSegmentPreview) -> AudienceSegmentPreview:
        model = AudienceSegmentPreviewModel(
            id=preview.id,
            segment_id=preview.segment_id,
            segment_label=preview.segment_label,
            legal_basis=preview.legal_basis,
            enabled=preview.enabled,
            status=preview.status,
            blocked_reasons=preview.blocked_reasons,
            total_volume=preview.total_volume,
            eligible_volume=preview.eligible_volume,
            exclusions_by_reason=preview.exclusions_by_reason,
            role_distribution=preview.role_distribution,
            module_distribution=preview.module_distribution,
            client_distribution=preview.client_distribution,
            created_at=preview.created_at,
        )
        self.session.add(model)
        for audit in preview.audits:
            self.session.add(
                AudienceSegmentAuditModel(
                    preview_id=preview.id,
                    contact_membership_id=audit.membership_id,
                    included=audit.included,
                    reasons=audit.reasons,
                    role_key=audit.role_key,
                    client_key=audit.client_key,
                )
            )
        self.session.commit()
        return preview

    def count_preview_audits(self, preview_id: str) -> int:
        return self.session.query(AudienceSegmentAuditModel).filter(AudienceSegmentAuditModel.preview_id == preview_id).count()
