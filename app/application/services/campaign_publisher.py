from __future__ import annotations

from datetime import UTC, datetime

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.operation_mode_service import OperationModeService
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.entities import CampaignRun, MauticCampaignPublication, Publication
from app.domain.errors import (
    CampaignNotFoundError,
    CampaignPublicationForbiddenError,
    DuplicateCampaignPublicationError,
    EmergencyStopActiveError,
)
from app.infrastructure.connectors.mautic import MauticConnector
from app.infrastructure.observability import structured_log
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.channel_operational_state import ChannelOperationalStateRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository


class CampaignPublisher:
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        review_portal: ReviewPortalService,
        segmentation_service: AudienceSegmentationService,
        mautic_repository: MauticPublicationRepository,
        mautic_sync_repository: MauticSyncRepository,
        mautic_connector: MauticConnector,
        audit_log: SqlAlchemyAuditLogRepository,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.review_portal = review_portal
        self.segmentation_service = segmentation_service
        self.mautic_repository = mautic_repository
        self.mautic_sync_repository = mautic_sync_repository
        self.mautic_connector = mautic_connector
        self.audit_log = audit_log
        self.settings = get_settings()
        self.operation_mode = OperationModeService()

    def create_preview(self, campaign_id: str, *, idempotency_key: str = "") -> dict:
        campaign, review, publication, contacts = self._prepare_context(campaign_id, idempotency_key=idempotency_key)
        category = self.mautic_connector.ensure_category(self.settings.mautic_category_name, bundle="email")
        email = self.mautic_connector.ensure_email_template(
            self._email_name(campaign, review),
            review.email_subject,
            review.email_html,
            category["id"],
        )
        publication.mautic_email_id = str(email["id"])
        publication = self.mautic_repository.save(publication)

        segment = self.mautic_connector.ensure_segment(
            alias=self._segment_alias(campaign, review),
            name=f"{campaign.name} v{review.content_version}",
            description=f"Campaign {campaign.id} review segment",
        )
        publication.mautic_segment_id = str(segment["id"])
        publication = self.mautic_repository.save(publication)
        for item in contacts:
            if item["mautic_contact_id"]:
                self.mautic_connector.add_contact_to_segment(item["mautic_contact_id"], publication.mautic_segment_id)

        mautic_campaign = self.mautic_connector.ensure_campaign(
            self._campaign_name(campaign, review),
            category["id"],
            is_published=False,
        )
        publication.mautic_campaign_id = str(mautic_campaign["id"])
        publication.status = "preview_ready"
        publication.target_instance_ids = sorted({item["instance_id"] for item in contacts})
        publication.target_client_ids = sorted({item["client_id"] for item in contacts})
        publication.targeted_contacts = len([item for item in contacts if item["mautic_contact_id"]])
        publication.last_error = ""
        publication = self.mautic_repository.save(publication)
        self.audit_log.append(
            campaign.id,
            "publication.preview_created",
            {"mautic_campaign_id": publication.mautic_campaign_id, "targeted_contacts": publication.targeted_contacts},
            actor_source="system",
            channel="mautic",
            result="SUCCESS",
        )
        return self._serialize(publication)

    def schedule_campaign(self, campaign_id: str, *, scheduled_at: datetime, idempotency_key: str = "") -> dict:
        campaign, review, publication, contacts = self._prepare_context(campaign_id, idempotency_key=idempotency_key)
        if publication.status == "scheduled":
            raise DuplicateCampaignPublicationError("This campaign version is already scheduled in Mautic.")
        self._enforce_kill_switches(contacts)
        self._verify_remote_dnc(contacts)
        preview = self.create_preview(campaign_id, idempotency_key=idempotency_key)
        publication = self.mautic_repository.get(campaign_id, review.content_version, review.segment_version)
        assert publication is not None
        self.mautic_connector.configure_campaign_delivery(
            publication.mautic_campaign_id,
            email_id=publication.mautic_email_id,
            segment_id=publication.mautic_segment_id,
            scheduled_at=scheduled_at.astimezone(UTC).isoformat(),
            is_published=False,
        )
        publication.status = "scheduled"
        publication.scheduled_at = scheduled_at.astimezone(UTC)
        publication.idempotency_key = idempotency_key
        publication.last_error = ""
        publication = self.mautic_repository.save(publication)
        if not any(item.channel == "mautic" for item in campaign.publications):
            campaign.publish(
                Publication(
                    campaign_run_id=campaign.id,
                    channel="mautic",
                    external_reference=publication.mautic_campaign_id,
                )
            )
            self.campaign_repository.save(campaign)
        self.audit_log.append(
            campaign.id,
            "publication.scheduled",
            {"mautic_campaign_id": publication.mautic_campaign_id, "scheduled_at": publication.scheduled_at.isoformat()},
            actor_source="system",
            channel="mautic",
            result="SUCCESS",
        )
        structured_log("campaign.mautic_scheduled", campaign_id=campaign.id, mautic_campaign_id=publication.mautic_campaign_id)
        return {**preview, **self._serialize(publication)}

    def _prepare_context(
        self,
        campaign_id: str,
        *,
        idempotency_key: str,
    ) -> tuple[CampaignRun, object, MauticCampaignPublication, list[dict]]:
        self.operation_mode.assert_real_mapsi_users_audience_disabled()
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        self.review_portal.ensure_publishable(campaign_id)
        review = self.review_portal.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            raise CampaignPublicationForbiddenError("Campaign review bundle is missing.")
        try:
            preview = self.segmentation_service.preview_segment(review.segment_id, persist=False)
        except ValueError as exc:
            raise CampaignPublicationForbiddenError(str(exc)) from exc
        if preview.status != "ready":
            raise CampaignPublicationForbiddenError("Audience segment is not ready for publication.")
        contacts = self.mautic_sync_repository.list_contacts_for_memberships(
            [audit.membership_id for audit in preview.audits if audit.included]
        )
        if not contacts:
            raise CampaignPublicationForbiddenError("No synced Mautic contacts available for the approved audience.")
        publication = self.mautic_repository.get(campaign_id, review.content_version, review.segment_version) or MauticCampaignPublication(
            campaign_run_id=campaign_id,
            content_version=review.content_version,
            segment_version=review.segment_version,
            idempotency_key=idempotency_key,
        )
        if publication.status == "scheduled" and publication.content_version == review.content_version:
            raise DuplicateCampaignPublicationError("This campaign version is already scheduled in Mautic.")
        return campaign, review, publication, [
            item
            for item in contacts
            if item["active"]
            and item["communication_eligible"]
            and not item["opted_out"]
            and item["email_valid"]
            and item["mautic_contact_id"]
        ]

    def _verify_remote_dnc(self, contacts: list[dict]) -> None:
        blocked = []
        for item in contacts:
            remote = self.mautic_connector.get_contact_dnc(item["mautic_contact_id"])
            if item["dnc_applied"] or item["remote_unsubscribed"] or remote:
                blocked.append(item["membership_id"])
        if blocked:
            raise CampaignPublicationForbiddenError("DNC verification failed just before scheduling.")

    def _enforce_kill_switches(self, contacts: list[dict]) -> None:
        operational = ChannelOperationalStateRepository(self.campaign_repository.session)
        if not operational.is_channel_feature_enabled(
            channel="mautic",
            static_default=True,
            safe_default_enabled=self.settings.channel_operational_safe_default_enabled,
        ):
            raise CampaignPublicationForbiddenError("MAUTIC publication channel is disabled.")
        if operational.is_channel_kill_switch_active("mautic"):
            raise EmergencyStopActiveError("Channel publication kill switch is active.")
        if operational.is_global_kill_switch_active(static_default=self.settings.workflow_kill_switch):
            raise EmergencyStopActiveError("Global publication kill switch is active.")
        blocked_instances = {item.strip() for item in self.settings.publication_instance_kill_switches.split(",") if item.strip()}
        blocked_clients = {item.strip() for item in self.settings.publication_client_kill_switches.split(",") if item.strip()}
        if any(item["instance_id"] in blocked_instances for item in contacts):
            raise EmergencyStopActiveError("Instance-level publication kill switch is active.")
        if any(item["client_id"] in blocked_clients for item in contacts):
            raise EmergencyStopActiveError("Client-level publication kill switch is active.")

    def _email_name(self, campaign: CampaignRun, review) -> str:
        return f"MGF {campaign.id} v{review.content_version} preview"

    def _segment_alias(self, campaign: CampaignRun, review) -> str:
        return f"mgf-{campaign.id}-v{review.content_version}".replace("_", "-")

    def _campaign_name(self, campaign: CampaignRun, review) -> str:
        return f"MGF {campaign.id} v{review.content_version} campaign"

    def _serialize(self, publication: MauticCampaignPublication) -> dict:
        return {
            "campaign_id": publication.campaign_run_id,
            "content_version": publication.content_version,
            "segment_version": publication.segment_version,
            "status": publication.status,
            "mautic_email_id": publication.mautic_email_id,
            "mautic_segment_id": publication.mautic_segment_id,
            "mautic_campaign_id": publication.mautic_campaign_id,
            "scheduled_at": publication.scheduled_at.isoformat() if publication.scheduled_at else None,
            "target_instance_ids": publication.target_instance_ids,
            "target_client_ids": publication.target_client_ids,
            "targeted_contacts": publication.targeted_contacts,
        }
