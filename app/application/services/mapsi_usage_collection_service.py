from __future__ import annotations

import hashlib
import hmac
from datetime import datetime

from dateutil.parser import isoparse

from app.core.config import get_settings
from app.core.security import encrypt_contact_value
from app.domain.entities import AudienceFact, CollectionRun
from app.generated.mapsi_contract_models import ContactEntry, UsageUser
from app.infrastructure.connectors.mapsi_usage import MapsiInstanceConfig, MapsiUsageConnector
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository


class MapsiUsageCollectionService:
    def __init__(
        self,
        connector: MapsiUsageConnector,
        repository: MapsiUsageRepository,
        instance_config: MapsiInstanceConfig,
    ) -> None:
        self.connector = connector
        self.repository = repository
        self.instance_config = instance_config
        self.settings = get_settings()

    def collect(self, dry_run: bool = False) -> dict:
        health = self.connector.health()
        capabilities = self.connector.capabilities()
        if health.contract_version.split(".", 1)[0] != "1":
            raise RuntimeError(f"Incompatible MAPSI contract version {health.contract_version}.")

        instance = self.repository.upsert_instance(
            instance_key=self.instance_config.id,
            base_url=self.instance_config.base_url,
            secret_ref=self.instance_config.secret_ref,
            enabled=self.instance_config.enabled,
            contract_version=health.contract_version,
        )
        run = self.repository.create_collection_run(instance.id, dry_run)
        previous_run = self.repository.get_latest_collection_run(instance.id)
        if previous_run is not None and previous_run.id != run.id and previous_run.status == "failed":
            run = self.repository.update_collection_run(
                run.id,
                last_usage_cursor=previous_run.last_usage_cursor,
                last_contact_cursor=previous_run.last_contact_cursor,
            )
        started = datetime.now()
        report = {
            "instances_succeeded": [],
            "instances_failed": [],
            "active_users": 0,
            "eligible_users": 0,
            "exclusions": {
                "disabled": 0,
                "opted_out": 0,
                "ineligible": 0,
            },
            "duration_seconds": 0.0,
        }
        try:
            for capability in capabilities.capabilities:
                if not dry_run:
                    self.repository.upsert_capability(instance.id, capability.capability_key, capability.enabled, capability.version)

            contact_map = self._collect_contacts(instance.id, run, dry_run)
            audience_facts = self._collect_usage(instance.id, run, contact_map, dry_run, report)
            report["instances_succeeded"].append(self.instance_config.id)
            report["audience_facts"] = len(audience_facts)
            run = self.repository.update_collection_run(
                run.id,
                status="completed",
                finished_at=datetime.now(),
                report=report,
            )
            report["duration_seconds"] = (datetime.now() - started).total_seconds()
            incr("mapsi_usage.collection.success")
            structured_log(
                "mapsi_usage.collection.completed",
                instance=self.instance_config.id,
                active_users=report["active_users"],
                eligible_users=report["eligible_users"],
                exclusions=report["exclusions"],
            )
            return report
        except Exception:
            report["instances_failed"].append(self.instance_config.id)
            self.repository.update_collection_run(
                run.id,
                status="failed",
                finished_at=datetime.now(),
                report=report,
            )
            incr("mapsi_usage.collection.failure")
            raise

    def _collect_contacts(self, instance_id: str, run: CollectionRun, dry_run: bool) -> dict[str, dict]:
        cursor = run.last_contact_cursor or None
        memberships: dict[str, dict] = {}
        while True:
            page = self.connector.contact_page(cursor=cursor, page_size=2)
            if page.contract_version.split(".", 1)[0] != "1":
                raise RuntimeError(f"Incompatible MAPSI contact contract version {page.contract_version}.")
            if not dry_run:
                self.repository.create_snapshot_if_absent(
                    instance_id,
                    "contact",
                    cursor or "",
                    page.contract_version,
                    isoparse(page.generated_at),
                )
            for contact in page.contacts:
                membership = self._store_contact(instance_id, contact, dry_run)
                memberships[contact.user_id] = membership
            cursor = page.next_cursor or None
            self.repository.update_collection_run(run.id, last_contact_cursor=cursor or "")
            if not page.has_more:
                break
        return memberships

    def _collect_usage(self, instance_id: str, run: CollectionRun, contact_map: dict[str, dict], dry_run: bool, report: dict) -> list[AudienceFact]:
        cursor = run.last_usage_cursor or None
        audience_facts: list[AudienceFact] = []
        while True:
            page = self.connector.usage_page(cursor=cursor, page_size=2)
            if page.contract_version.split(".", 1)[0] != "1":
                raise RuntimeError(f"Incompatible MAPSI usage contract version {page.contract_version}.")
            snapshot = None
            if not dry_run:
                snapshot = self.repository.create_snapshot_if_absent(
                    instance_id,
                    "usage",
                    cursor or "",
                    page.contract_version,
                    isoparse(page.captured_at),
                )
            for user in page.users:
                membership_info = contact_map.get(user.user_id)
                if membership_info is None:
                    continue
                membership_id = membership_info["membership_id"]
                report["active_users"] += int(user.active)
                if not user.active:
                    report["exclusions"]["disabled"] += 1
                if user.opted_out:
                    report["exclusions"]["opted_out"] += 1
                if not user.communication_eligible:
                    report["exclusions"]["ineligible"] += 1
                if user.active and user.communication_eligible and not user.opted_out:
                    report["eligible_users"] += 1
                if not dry_run:
                    self.repository.upsert_contact_membership(
                        contact_identity_id=membership_info["contact_identity_id"],
                        customer_account_id=membership_info["customer_account_id"],
                        external_user_id=user.user_id,
                        role_key=user.role_key,
                        active=user.active,
                        communication_eligible=bool(user.communication_eligible),
                        opted_out=bool(user.opted_out),
                        last_activity_at=isoparse(user.last_activity_at),
                    )
                if not dry_run and snapshot is not None:
                    for module in user.modules:
                        self.repository.upsert_feature_adoption(snapshot.id, membership_id, module.module_key, module.events_last_7_days)
                audience_facts.append(
                    AudienceFact(
                        membership_id=membership_id,
                        customer_account_id=membership_info["customer_account_id"],
                        client_key=membership_info["client_key"],
                        role_key=user.role_key,
                        active=user.active,
                        communication_eligible=bool(user.communication_eligible),
                        opted_out=bool(user.opted_out),
                        module_keys=[module.module_key for module in user.modules],
                        module_events={module.module_key: module.events_last_7_days for module in user.modules},
                        instance_key=self.instance_config.id,
                        created_at=membership_info["created_at"],
                        last_activity_at=isoparse(user.last_activity_at),
                    )
                )
            cursor = page.next_cursor or None
            self.repository.update_collection_run(run.id, last_usage_cursor=cursor or "")
            if not page.has_more:
                break
        return audience_facts

    def _store_contact(self, instance_id: str, contact: ContactEntry, dry_run: bool) -> dict:
        if dry_run:
            return {
                "membership_id": f"dry-run:{contact.user_id}",
                "contact_identity_id": f"dry-run:identity:{contact.user_id}",
                "customer_account_id": f"dry-run:account:{contact.tenant_id}",
                "client_key": contact.tenant_id,
                "created_at": datetime.now().astimezone(),
            }
        account = self.repository.upsert_customer_account(instance_id, contact.tenant_id)
        identity = self.repository.upsert_contact_identity(
            self._hash_email(contact.email),
            encrypt_contact_value(contact.email),
            self._is_email_valid(contact.email),
        )
        membership = self.repository.upsert_contact_membership(
            contact_identity_id=identity.id,
            customer_account_id=account.id,
            external_user_id=contact.user_id,
            role_key=contact.role_key or "",
            active=contact.active,
            communication_eligible=contact.communication_eligible,
            opted_out=bool(contact.opted_out),
            last_activity_at=None,
        )
        return {
            "membership_id": membership.id,
            "contact_identity_id": identity.id,
            "customer_account_id": account.id,
            "client_key": account.external_account_id,
            "created_at": membership.created_at,
        }

    def _hash_email(self, email: str) -> str:
        normalized = email.strip().lower().encode("utf-8")
        salt = self.settings.contact_hash_salt.encode("utf-8")
        return hmac.new(salt, normalized, hashlib.sha256).hexdigest()

    def _is_email_valid(self, email: str) -> bool:
        normalized = email.strip()
        return "@" in normalized and "." in normalized.rsplit("@", 1)[-1]
