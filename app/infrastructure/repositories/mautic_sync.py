from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import decrypt_contact_value
from app.domain.entities import MauticContactLink
from app.infrastructure.db.models import (
    ContactIdentityModel,
    ContactMembershipModel,
    CustomerAccountModel,
    FeatureAdoptionModel,
    MauticContactLinkModel,
    MapsiInstanceModel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MauticSyncRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_sync_candidates(self) -> list[dict]:
        rows = (
            self.session.query(
                ContactIdentityModel,
                ContactMembershipModel,
                CustomerAccountModel.external_account_id,
                MapsiInstanceModel.instance_key,
                FeatureAdoptionModel.module_key,
                FeatureAdoptionModel.events_last_7_days,
            )
            .join(ContactMembershipModel, ContactMembershipModel.contact_identity_id == ContactIdentityModel.id)
            .join(CustomerAccountModel, CustomerAccountModel.id == ContactMembershipModel.customer_account_id)
            .join(MapsiInstanceModel, MapsiInstanceModel.id == CustomerAccountModel.mapsi_instance_id)
            .outerjoin(FeatureAdoptionModel, FeatureAdoptionModel.contact_membership_id == ContactMembershipModel.id)
            .all()
        )
        grouped: dict[str, dict] = {}
        for identity, membership, customer_id, instance_id, module_key, events in rows:
            item = grouped.setdefault(
                identity.id,
                {
                    "contact_identity_id": identity.id,
                    "email_hash": identity.email_hash,
                    "encrypted_email": identity.encrypted_email,
                    "email_valid": identity.email_valid,
                    "memberships": {},
                    "membership_ids": set(),
                    "customer_ids": set(),
                    "instance_ids": set(),
                    "roles": set(),
                    "modules": set(),
                    "module_events": defaultdict(int),
                    "last_login_at": None,
                    "source_updated_at": identity.created_at,
                },
            )
            current = item["memberships"].setdefault(
                membership.id,
                {
                    "active": membership.active,
                    "communication_eligible": membership.communication_eligible,
                    "opted_out": membership.opted_out,
                },
            )
            current["active"] = membership.active
            current["communication_eligible"] = membership.communication_eligible
            current["opted_out"] = membership.opted_out
            item["membership_ids"].add(membership.id)
            item["customer_ids"].add(customer_id)
            item["instance_ids"].add(instance_id)
            if membership.role_key:
                item["roles"].add(membership.role_key)
            if module_key:
                item["modules"].add(module_key)
                item["module_events"][module_key] = max(item["module_events"][module_key], events or 0)
            if membership.last_activity_at and (
                item["last_login_at"] is None or membership.last_activity_at > item["last_login_at"]
            ):
                item["last_login_at"] = membership.last_activity_at
            if membership.updated_at > item["source_updated_at"]:
                item["source_updated_at"] = membership.updated_at
        results: list[dict] = []
        for item in grouped.values():
            memberships = list(item["memberships"].values())
            active = any(member["active"] for member in memberships)
            eligible = any(
                member["active"] and member["communication_eligible"] and not member["opted_out"]
                for member in memberships
            )
            opted_out = any(member["opted_out"] for member in memberships)
            total_events = sum(item["module_events"].values())
            usage_level = "high" if total_events >= 10 else "medium" if total_events >= 3 else "low"
            feature_gaps = sorted(module for module, value in item["module_events"].items() if value == 0)
            results.append(
                {
                    "contact_identity_id": item["contact_identity_id"],
                    "email_hash": item["email_hash"],
                    "email": decrypt_contact_value(item["encrypted_email"]) if item["encrypted_email"] else "",
                    "email_valid": item["email_valid"],
                    "mapsi_contact_key": item["email_hash"],
                    "mapsi_customer_ids": sorted(item["customer_ids"]),
                    "mapsi_instance_ids": sorted(item["instance_ids"]),
                    "membership_ids": sorted(item["membership_ids"]),
                    "mapsi_roles": sorted(item["roles"]),
                    "mapsi_modules": sorted(item["modules"]),
                    "mapsi_last_login_at": item["last_login_at"],
                    "mapsi_usage_level": usage_level,
                    "mapsi_feature_gaps": feature_gaps,
                    "mapsi_active": active,
                    "mapsi_communication_eligible": eligible,
                    "mapsi_legal_basis": "legitimate_interest_growth" if eligible else "",
                    "mapsi_opt_out": opted_out,
                    "mapsi_source_updated_at": item["source_updated_at"],
                }
            )
        return results

    def get_link(self, contact_identity_id: str) -> MauticContactLink | None:
        model = (
            self.session.query(MauticContactLinkModel)
            .filter(MauticContactLinkModel.contact_identity_id == contact_identity_id)
            .one_or_none()
        )
        if model is None:
            return None
        return self._to_entity(model)

    def list_contacts_for_memberships(self, membership_ids: list[str]) -> list[dict]:
        if not membership_ids:
            return []
        rows = (
            self.session.query(
                ContactMembershipModel.id,
                ContactMembershipModel.active,
                ContactMembershipModel.communication_eligible,
                ContactMembershipModel.opted_out,
                CustomerAccountModel.external_account_id,
                MapsiInstanceModel.instance_key,
                ContactIdentityModel.email_valid,
                MauticContactLinkModel.mautic_contact_id,
                MauticContactLinkModel.dnc_applied,
                MauticContactLinkModel.remote_unsubscribed,
            )
            .join(ContactIdentityModel, ContactIdentityModel.id == ContactMembershipModel.contact_identity_id)
            .join(CustomerAccountModel, CustomerAccountModel.id == ContactMembershipModel.customer_account_id)
            .join(MapsiInstanceModel, MapsiInstanceModel.id == CustomerAccountModel.mapsi_instance_id)
            .outerjoin(MauticContactLinkModel, MauticContactLinkModel.contact_identity_id == ContactIdentityModel.id)
            .filter(ContactMembershipModel.id.in_(membership_ids))
            .all()
        )
        return [
            {
                "membership_id": membership_id,
                "active": active,
                "communication_eligible": communication_eligible,
                "opted_out": opted_out,
                "client_id": client_id,
                "instance_id": instance_id,
                "email_valid": email_valid,
                "mautic_contact_id": mautic_contact_id or "",
                "dnc_applied": dnc_applied if dnc_applied is not None else False,
                "remote_unsubscribed": remote_unsubscribed if remote_unsubscribed is not None else False,
            }
            for (
                membership_id,
                active,
                communication_eligible,
                opted_out,
                client_id,
                instance_id,
                email_valid,
                mautic_contact_id,
                dnc_applied,
                remote_unsubscribed,
            ) in rows
        ]

    def get_contact_keys_by_mautic_ids(self, mautic_contact_ids: list[str]) -> dict[str, dict]:
        if not mautic_contact_ids:
            return {}
        rows = (
            self.session.query(
                MauticContactLinkModel.mautic_contact_id,
                MauticContactLinkModel.email_hash,
                ContactMembershipModel.id,
                CustomerAccountModel.external_account_id,
                MapsiInstanceModel.instance_key,
            )
            .join(ContactIdentityModel, ContactIdentityModel.id == MauticContactLinkModel.contact_identity_id)
            .join(ContactMembershipModel, ContactMembershipModel.contact_identity_id == ContactIdentityModel.id)
            .join(CustomerAccountModel, CustomerAccountModel.id == ContactMembershipModel.customer_account_id)
            .join(MapsiInstanceModel, MapsiInstanceModel.id == CustomerAccountModel.mapsi_instance_id)
            .filter(MauticContactLinkModel.mautic_contact_id.in_(mautic_contact_ids))
            .all()
        )
        result: dict[str, dict] = {}
        for mautic_contact_id, email_hash, membership_id, client_id, instance_id in rows:
            current = result.setdefault(
                mautic_contact_id,
                {
                    "contact_key": email_hash,
                    "membership_ids": [],
                    "client_ids": set(),
                    "instance_ids": set(),
                },
            )
            current["membership_ids"].append(membership_id)
            current["client_ids"].add(client_id)
            current["instance_ids"].add(instance_id)
        for item in result.values():
            item["client_ids"] = sorted(item["client_ids"])
            item["instance_ids"] = sorted(item["instance_ids"])
        return result

    def upsert_link(
        self,
        *,
        contact_identity_id: str,
        mautic_contact_id: str,
        email_hash: str,
        dnc_applied: bool,
        remote_unsubscribed: bool,
        last_sync_status: str,
        last_source_updated_at: datetime | None,
    ) -> MauticContactLink:
        model = (
            self.session.query(MauticContactLinkModel)
            .filter(MauticContactLinkModel.contact_identity_id == contact_identity_id)
            .one_or_none()
        )
        if model is None:
            model = MauticContactLinkModel(contact_identity_id=contact_identity_id, mautic_contact_id=mautic_contact_id, email_hash=email_hash)
            self.session.add(model)
        model.mautic_contact_id = mautic_contact_id
        model.email_hash = email_hash
        model.dnc_applied = dnc_applied
        model.remote_unsubscribed = remote_unsubscribed
        model.last_sync_status = last_sync_status
        model.last_synced_at = utcnow()
        model.last_source_updated_at = last_source_updated_at
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def _to_entity(self, model: MauticContactLinkModel) -> MauticContactLink:
        return MauticContactLink(
            id=model.id,
            contact_identity_id=model.contact_identity_id,
            mautic_contact_id=model.mautic_contact_id,
            email_hash=model.email_hash,
            dnc_applied=model.dnc_applied,
            remote_unsubscribed=model.remote_unsubscribed,
            last_sync_status=model.last_sync_status,
            last_synced_at=model.last_synced_at,
            last_source_updated_at=model.last_source_updated_at,
            created_at=model.created_at,
        )
