from __future__ import annotations

from datetime import datetime
from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.core.config import get_settings
from app.infrastructure.connectors.mautic import MauticConnector
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository

CUSTOM_FIELDS = [
    ("mapsi_contact_key", "MAPSI Contact Key"),
    ("mapsi_customer_ids", "MAPSI Customer IDs"),
    ("mapsi_instance_ids", "MAPSI Instance IDs"),
    ("mapsi_roles", "MAPSI Roles"),
    ("mapsi_modules", "MAPSI Modules"),
    ("mapsi_last_login_at", "MAPSI Last Login At"),
    ("mapsi_usage_level", "MAPSI Usage Level"),
    ("mapsi_feature_gaps", "MAPSI Feature Gaps"),
    ("mapsi_active", "MAPSI Active"),
    ("mapsi_communication_eligible", "MAPSI Communication Eligible"),
    ("mapsi_legal_basis", "MAPSI Legal Basis"),
    ("mapsi_opt_out", "MAPSI Opt Out"),
    ("mapsi_source_updated_at", "MAPSI Source Updated At"),
]
TAGS = ["mapsi", "mapsi-growth", "mapsi-eligible", "mapsi-dnc"]


class MauticContactSyncService:
    def __init__(
        self,
        connector: MauticConnector,
        repository: MauticSyncRepository,
        segmentation_service: AudienceSegmentationService,
    ) -> None:
        self.connector = connector
        self.repository = repository
        self.segmentation_service = segmentation_service
        self.settings = get_settings()

    def provision(self, dry_run: bool = False) -> dict:
        segment_rules = self.segmentation_service.list_segments(enabled_only=True)
        report = {
            "custom_fields": len(CUSTOM_FIELDS),
            "tags": len(TAGS),
            "segments": len(segment_rules),
            "categories": 1,
            "emails": 1,
            "campaigns": 1,
            "dry_run": dry_run,
        }
        if dry_run:
            return report
        for alias, label in CUSTOM_FIELDS:
            field_type = "bool" if alias in {"mapsi_active", "mapsi_communication_eligible", "mapsi_opt_out"} else "text"
            self.connector.ensure_custom_field(alias, label, field_type=field_type)
        for tag in TAGS:
            self.connector.ensure_tag(tag)
        category = self.connector.ensure_category(self.settings.mautic_category_name, bundle="email")
        for rule in segment_rules:
            self.connector.ensure_segment(rule.id, rule.label, rule.description or rule.id)
        self.connector.ensure_email_template(
            self.settings.mautic_weekly_template_name,
            "MAPSI weekly update",
            "<html><body><h1>MAPSI weekly update</h1><p>Template disabled by default.</p></body></html>",
            category["id"],
        )
        self.connector.ensure_campaign(self.settings.mautic_weekly_campaign_name, category["id"], is_published=False)
        return report

    def sync_contacts(self, dry_run: bool = False) -> dict:
        started = datetime.now()
        candidates = self.repository.list_sync_candidates()
        report = {
            "contacts_seen": len(candidates),
            "contacts_synced": 0,
            "contacts_dnc": 0,
            "contacts_skipped": 0,
            "instances": 0,
            "customers": 0,
            "dry_run": dry_run,
            "duration_seconds": 0.0,
            "statuses": {"synced": 0, "dnc": 0, "skipped": 0},
        }
        seen_instances = set()
        seen_customers = set()
        for candidate in candidates:
            seen_instances.update(candidate["mapsi_instance_ids"])
            seen_customers.update(candidate["mapsi_customer_ids"])
            status = self._sync_candidate(candidate, dry_run=dry_run)
            report["statuses"][status] += 1
            if status == "synced":
                report["contacts_synced"] += 1
            elif status == "dnc":
                report["contacts_dnc"] += 1
            else:
                report["contacts_skipped"] += 1
        report["instances"] = len(seen_instances)
        report["customers"] = len(seen_customers)
        report["duration_seconds"] = (datetime.now() - started).total_seconds()
        incr("mautic.sync.completed")
        structured_log(
            "mautic.sync.completed",
            contacts_seen=report["contacts_seen"],
            contacts_synced=report["contacts_synced"],
            contacts_dnc=report["contacts_dnc"],
            contacts_skipped=report["contacts_skipped"],
        )
        return report

    def _sync_candidate(self, candidate: dict, *, dry_run: bool) -> str:
        link = self.repository.get_link(candidate["contact_identity_id"])
        invalid_email = not candidate["email_valid"] or not candidate["email"]
        should_dnc = invalid_email or candidate["mapsi_opt_out"] or not candidate["mapsi_active"] or not candidate["mapsi_communication_eligible"]
        if link is not None and (link.dnc_applied or link.remote_unsubscribed):
            if not dry_run:
                self.repository.upsert_link(
                    contact_identity_id=candidate["contact_identity_id"],
                    mautic_contact_id=link.mautic_contact_id,
                    email_hash=candidate["email_hash"],
                    dnc_applied=True,
                    remote_unsubscribed=link.remote_unsubscribed,
                    last_sync_status="dnc",
                    last_source_updated_at=candidate["mapsi_source_updated_at"],
                )
            return "dnc"
        remote_contact = None if invalid_email else self.connector.find_contact_by_email(candidate["email"])
        remote_unsubscribed = False
        if remote_contact is not None:
            remote_unsubscribed = bool(remote_contact.get("isDoNotContact")) or bool(remote_contact.get("unsubscribed"))
        if should_dnc:
            if remote_contact is None:
                return "skipped" if dry_run else "skipped"
            if not dry_run:
                self.connector.add_do_not_contact(remote_contact["id"], reason="mapsi_sync_exclusion")
                self.repository.upsert_link(
                    contact_identity_id=candidate["contact_identity_id"],
                    mautic_contact_id=str(remote_contact["id"]),
                    email_hash=candidate["email_hash"],
                    dnc_applied=True,
                    remote_unsubscribed=remote_unsubscribed,
                    last_sync_status="dnc",
                    last_source_updated_at=candidate["mapsi_source_updated_at"],
                )
            return "dnc"
        if remote_unsubscribed:
            if not dry_run and remote_contact is not None:
                self.repository.upsert_link(
                    contact_identity_id=candidate["contact_identity_id"],
                    mautic_contact_id=str(remote_contact["id"]),
                    email_hash=candidate["email_hash"],
                    dnc_applied=True,
                    remote_unsubscribed=True,
                    last_sync_status="dnc",
                    last_source_updated_at=candidate["mapsi_source_updated_at"],
                )
            return "dnc"
        fields = {
            "firstname": "",
            "lastname": "",
            "mapsi_contact_key": candidate["mapsi_contact_key"],
            "mapsi_customer_ids": ",".join(candidate["mapsi_customer_ids"]),
            "mapsi_instance_ids": ",".join(candidate["mapsi_instance_ids"]),
            "mapsi_roles": ",".join(candidate["mapsi_roles"]),
            "mapsi_modules": ",".join(candidate["mapsi_modules"]),
            "mapsi_last_login_at": candidate["mapsi_last_login_at"].isoformat() if candidate["mapsi_last_login_at"] else "",
            "mapsi_usage_level": candidate["mapsi_usage_level"],
            "mapsi_feature_gaps": ",".join(candidate["mapsi_feature_gaps"]),
            "mapsi_active": candidate["mapsi_active"],
            "mapsi_communication_eligible": candidate["mapsi_communication_eligible"],
            "mapsi_legal_basis": candidate["mapsi_legal_basis"],
            "mapsi_opt_out": candidate["mapsi_opt_out"],
            "mapsi_source_updated_at": candidate["mapsi_source_updated_at"].isoformat() if candidate["mapsi_source_updated_at"] else "",
        }
        if dry_run:
            return "synced"
        contact = self.connector.upsert_contact(candidate["email"], fields, tags=["mapsi", "mapsi-growth", "mapsi-eligible"])
        for rule in self.segmentation_service.list_segments(enabled_only=True):
            segment = self.connector.ensure_segment(rule.id, rule.label, rule.description or rule.id)
            preview = self.segmentation_service.preview_segment(rule.id, persist=False)
            if any(audit.membership_id in candidate["membership_ids"] and audit.included for audit in preview.audits):
                self.connector.add_contact_to_segment(contact["id"], segment["id"])
        self.repository.upsert_link(
            contact_identity_id=candidate["contact_identity_id"],
            mautic_contact_id=str(contact["id"]),
            email_hash=candidate["email_hash"],
            dnc_applied=False,
            remote_unsubscribed=False,
            last_sync_status="synced",
            last_source_updated_at=candidate["mapsi_source_updated_at"],
        )
        return "synced"
