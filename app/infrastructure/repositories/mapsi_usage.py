from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.domain.entities import (
    CollectionRun,
    ContactIdentity,
    ContactMembership,
    CustomerAccount,
    FeatureAdoption,
    InstanceCapability,
    MapsiInstance,
    UsageSnapshotRecord,
)
from app.infrastructure.db.models import (
    CollectionRunModel,
    ContactIdentityModel,
    ContactMembershipModel,
    CustomerAccountModel,
    FeatureAdoptionModel,
    InstanceCapabilityModel,
    MapsiInstanceModel,
    UsageSnapshotModel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MapsiUsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_instance(self, instance_key: str, base_url: str, secret_ref: str, enabled: bool, contract_version: str) -> MapsiInstance:
        model = self.session.query(MapsiInstanceModel).filter(MapsiInstanceModel.instance_key == instance_key).one_or_none()
        if model is None:
            model = MapsiInstanceModel(
                instance_key=instance_key,
                base_url=base_url,
                secret_ref=secret_ref,
                enabled=enabled,
                contract_version=contract_version,
            )
            self.session.add(model)
        else:
            model.base_url = base_url
            model.secret_ref = secret_ref
            model.enabled = enabled
            model.contract_version = contract_version
        self.session.commit()
        self.session.refresh(model)
        return MapsiInstance(
            id=model.id,
            instance_key=model.instance_key,
            base_url=model.base_url,
            secret_ref=model.secret_ref,
            enabled=model.enabled,
            contract_version=model.contract_version,
            created_at=model.created_at,
        )

    def get_instance(self, instance_key: str) -> MapsiInstance | None:
        model = self.session.query(MapsiInstanceModel).filter(MapsiInstanceModel.instance_key == instance_key).one_or_none()
        if model is None:
            return None
        return MapsiInstance(
            id=model.id,
            instance_key=model.instance_key,
            base_url=model.base_url,
            secret_ref=model.secret_ref,
            enabled=model.enabled,
            contract_version=model.contract_version,
            created_at=model.created_at,
        )

    def list_instances(self) -> list[MapsiInstance]:
        models = self.session.query(MapsiInstanceModel).all()
        return [
            MapsiInstance(
                id=model.id,
                instance_key=model.instance_key,
                base_url=model.base_url,
                secret_ref=model.secret_ref,
                enabled=model.enabled,
                contract_version=model.contract_version,
                created_at=model.created_at,
            )
            for model in models
        ]

    def upsert_customer_account(self, mapsi_instance_id: str, external_account_id: str) -> CustomerAccount:
        model = (
            self.session.query(CustomerAccountModel)
            .filter(
                CustomerAccountModel.mapsi_instance_id == mapsi_instance_id,
                CustomerAccountModel.external_account_id == external_account_id,
            )
            .one_or_none()
        )
        if model is None:
            model = CustomerAccountModel(mapsi_instance_id=mapsi_instance_id, external_account_id=external_account_id)
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
        return CustomerAccount(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            external_account_id=model.external_account_id,
            created_at=model.created_at,
        )

    def upsert_contact_identity(self, email_hash: str, encrypted_email: str, email_valid: bool) -> ContactIdentity:
        model = self.session.query(ContactIdentityModel).filter(ContactIdentityModel.email_hash == email_hash).one_or_none()
        if model is None:
            model = ContactIdentityModel(email_hash=email_hash, encrypted_email=encrypted_email, email_valid=email_valid)
            self.session.add(model)
        else:
            model.encrypted_email = encrypted_email
            model.email_valid = email_valid
        self.session.commit()
        self.session.refresh(model)
        return ContactIdentity(
            id=model.id,
            email_hash=model.email_hash,
            encrypted_email=model.encrypted_email,
            email_valid=model.email_valid,
            created_at=model.created_at,
        )

    def upsert_contact_membership(
        self,
        *,
        contact_identity_id: str,
        customer_account_id: str,
        external_user_id: str,
        role_key: str,
        active: bool,
        communication_eligible: bool,
        opted_out: bool,
        last_activity_at: datetime | None,
    ) -> ContactMembership:
        model = (
            self.session.query(ContactMembershipModel)
            .filter(
                ContactMembershipModel.contact_identity_id == contact_identity_id,
                ContactMembershipModel.customer_account_id == customer_account_id,
                ContactMembershipModel.external_user_id == external_user_id,
            )
            .one_or_none()
        )
        if model is None:
            model = ContactMembershipModel(
                contact_identity_id=contact_identity_id,
                customer_account_id=customer_account_id,
                external_user_id=external_user_id,
            )
            self.session.add(model)
        model.role_key = role_key
        model.active = active
        model.communication_eligible = communication_eligible
        model.opted_out = opted_out
        model.last_activity_at = last_activity_at
        model.updated_at = utcnow()
        self.session.commit()
        self.session.refresh(model)
        return ContactMembership(
            id=model.id,
            contact_identity_id=model.contact_identity_id,
            customer_account_id=model.customer_account_id,
            external_user_id=model.external_user_id,
            role_key=model.role_key,
            active=model.active,
            communication_eligible=model.communication_eligible,
            opted_out=model.opted_out,
            last_activity_at=model.last_activity_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def create_snapshot_if_absent(
        self,
        mapsi_instance_id: str,
        snapshot_kind: str,
        source_cursor: str,
        contract_version: str,
        source_generated_at: datetime | None,
    ) -> UsageSnapshotRecord:
        model = (
            self.session.query(UsageSnapshotModel)
            .filter(
                UsageSnapshotModel.mapsi_instance_id == mapsi_instance_id,
                UsageSnapshotModel.snapshot_kind == snapshot_kind,
                UsageSnapshotModel.source_cursor == source_cursor,
            )
            .one_or_none()
        )
        if model is None:
            model = UsageSnapshotModel(
                mapsi_instance_id=mapsi_instance_id,
                snapshot_kind=snapshot_kind,
                source_cursor=source_cursor,
                contract_version=contract_version,
                source_generated_at=source_generated_at,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
        return UsageSnapshotRecord(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            snapshot_kind=model.snapshot_kind,
            source_cursor=model.source_cursor,
            contract_version=model.contract_version,
            collected_at=model.collected_at,
            source_generated_at=model.source_generated_at,
        )

    def upsert_feature_adoption(
        self,
        usage_snapshot_id: str,
        contact_membership_id: str,
        module_key: str,
        events_last_7_days: int,
    ) -> FeatureAdoption:
        model = (
            self.session.query(FeatureAdoptionModel)
            .filter(
                FeatureAdoptionModel.usage_snapshot_id == usage_snapshot_id,
                FeatureAdoptionModel.contact_membership_id == contact_membership_id,
                FeatureAdoptionModel.module_key == module_key,
            )
            .one_or_none()
        )
        if model is None:
            model = FeatureAdoptionModel(
                usage_snapshot_id=usage_snapshot_id,
                contact_membership_id=contact_membership_id,
                module_key=module_key,
            )
            self.session.add(model)
        model.events_last_7_days = events_last_7_days
        self.session.commit()
        self.session.refresh(model)
        return FeatureAdoption(
            id=model.id,
            usage_snapshot_id=model.usage_snapshot_id,
            contact_membership_id=model.contact_membership_id,
            module_key=model.module_key,
            events_last_7_days=model.events_last_7_days,
            created_at=model.created_at,
        )

    def upsert_capability(self, mapsi_instance_id: str, capability_key: str, enabled: bool, version: str) -> InstanceCapability:
        model = (
            self.session.query(InstanceCapabilityModel)
            .filter(
                InstanceCapabilityModel.mapsi_instance_id == mapsi_instance_id,
                InstanceCapabilityModel.capability_key == capability_key,
            )
            .one_or_none()
        )
        if model is None:
            model = InstanceCapabilityModel(mapsi_instance_id=mapsi_instance_id, capability_key=capability_key)
            self.session.add(model)
        model.enabled = enabled
        model.version = version
        model.collected_at = utcnow()
        self.session.commit()
        self.session.refresh(model)
        return InstanceCapability(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            capability_key=model.capability_key,
            enabled=model.enabled,
            version=model.version,
            collected_at=model.collected_at,
        )

    def list_capabilities(self) -> list[InstanceCapability]:
        models = self.session.query(InstanceCapabilityModel).all()
        return [
            InstanceCapability(
                id=model.id,
                mapsi_instance_id=model.mapsi_instance_id,
                capability_key=model.capability_key,
                enabled=model.enabled,
                version=model.version,
                collected_at=model.collected_at,
            )
            for model in models
        ]

    def usage_window_totals(self, membership_ids: list[str], *, start: datetime | None, end: datetime) -> dict[str, int]:
        if not membership_ids:
            return {}
        timestamp = func.coalesce(UsageSnapshotModel.source_generated_at, UsageSnapshotModel.collected_at)
        query = (
            self.session.query(
                FeatureAdoptionModel.contact_membership_id,
                func.sum(FeatureAdoptionModel.events_last_7_days),
            )
            .join(UsageSnapshotModel, UsageSnapshotModel.id == FeatureAdoptionModel.usage_snapshot_id)
            .filter(FeatureAdoptionModel.contact_membership_id.in_(membership_ids))
            .filter(timestamp <= end)
        )
        if start is not None:
            query = query.filter(timestamp >= start)
        rows = query.group_by(FeatureAdoptionModel.contact_membership_id).all()
        return {membership_id: int(total or 0) for membership_id, total in rows}

    def activity_summary(self, membership_ids: list[str], *, reference_at: datetime, after_days: int) -> dict[str, int]:
        if not membership_ids:
            return {"connected_after_window": 0, "reactivated_users": 0}
        rows = (
            self.session.query(ContactMembershipModel)
            .filter(ContactMembershipModel.id.in_(membership_ids))
            .all()
        )
        connected = 0
        reactivated = 0
        for row in rows:
            if row.last_activity_at is None:
                continue
            if reference_at <= row.last_activity_at <= reference_at + timedelta(days=after_days):
                connected += 1
                if row.last_activity_at - timedelta(days=30) > (row.created_at or row.last_activity_at):
                    reactivated += 1
        return {"connected_after_window": connected, "reactivated_users": reactivated}

    def create_collection_run(self, mapsi_instance_id: str, dry_run: bool) -> CollectionRun:
        model = CollectionRunModel(mapsi_instance_id=mapsi_instance_id, dry_run=dry_run)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return CollectionRun(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            status=model.status,
            dry_run=model.dry_run,
            started_at=model.started_at,
            finished_at=model.finished_at,
            last_usage_cursor=model.last_usage_cursor,
            last_contact_cursor=model.last_contact_cursor,
            report=model.report,
        )

    def get_latest_collection_run(self, mapsi_instance_id: str) -> CollectionRun | None:
        model = (
            self.session.query(CollectionRunModel)
            .filter(CollectionRunModel.mapsi_instance_id == mapsi_instance_id)
            .order_by(CollectionRunModel.started_at.desc())
            .first()
        )
        if model is None:
            return None
        return CollectionRun(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            status=model.status,
            dry_run=model.dry_run,
            started_at=model.started_at,
            finished_at=model.finished_at,
            last_usage_cursor=model.last_usage_cursor,
            last_contact_cursor=model.last_contact_cursor,
            report=model.report,
        )

    def update_collection_run(self, run_id: str, **fields) -> CollectionRun:
        model = self.session.query(CollectionRunModel).filter(CollectionRunModel.id == run_id).one()
        for key, value in fields.items():
            setattr(model, key, value)
        self.session.commit()
        self.session.refresh(model)
        return CollectionRun(
            id=model.id,
            mapsi_instance_id=model.mapsi_instance_id,
            status=model.status,
            dry_run=model.dry_run,
            started_at=model.started_at,
            finished_at=model.finished_at,
            last_usage_cursor=model.last_usage_cursor,
            last_contact_cursor=model.last_contact_cursor,
            report=model.report,
        )
