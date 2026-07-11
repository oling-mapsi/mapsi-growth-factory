from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.domain.entities import Interaction
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError
from app.infrastructure.connectors.mautic import MauticConnector
from app.infrastructure.observability import structured_log
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository


ALLOWED_EVENT_TYPES = {
    "sent",
    "delivered",
    "opened",
    "clicked",
    "bounced",
    "unsubscribed",
    "complaint",
}


class AdoptionMeasurementService:
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        mautic_publications: MauticPublicationRepository,
        mautic_sync_repository: MauticSyncRepository,
        mapsi_usage_repository: MapsiUsageRepository,
        review_repository: ReviewPortalRepository,
        mautic_connector: MauticConnector,
        audit_log: SqlAlchemyAuditLogRepository,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.mautic_publications = mautic_publications
        self.mautic_sync_repository = mautic_sync_repository
        self.mapsi_usage_repository = mapsi_usage_repository
        self.review_repository = review_repository
        self.mautic_connector = mautic_connector
        self.audit_log = audit_log
        self.settings = get_settings()

    def import_events(self, campaign_id: str) -> dict:
        campaign, publication, review = self._context(campaign_id)
        raw_events = self.mautic_connector.list_campaign_events(publication.mautic_campaign_id)
        contact_map = self.mautic_sync_repository.get_contact_keys_by_mautic_ids(
            sorted({str(item.get("contactId", "")) for item in raw_events if item.get("contactId")})
        )
        existing_ids = {
            interaction.metadata.get("event_id")
            for interaction in campaign.interactions
            if interaction.interaction_type.startswith("mautic.")
        }
        imported = 0
        skipped = 0
        for item in raw_events:
            event_type = str(item.get("type", "")).lower()
            event_id = str(item.get("id", ""))
            if event_type not in ALLOWED_EVENT_TYPES or event_id in existing_ids:
                skipped += 1
                continue
            mapping = contact_map.get(str(item.get("contactId", "")))
            if mapping is None:
                skipped += 1
                continue
            campaign.interactions.append(
                Interaction(
                    campaign_run_id=campaign.id,
                    interaction_type=f"mautic.{event_type}",
                    occurred_at=self._parse_datetime(item.get("occurredAt")),
                    metadata={
                        "event_id": event_id,
                        "campaign_id": campaign.id,
                        "asset_version": publication.content_version,
                        "audience_segment_id": review.segment_id,
                        "contact_key": mapping["contact_key"],
                        "membership_ids": mapping["membership_ids"],
                        "client_ids": mapping["client_ids"],
                        "instance_ids": mapping["instance_ids"],
                    },
                )
            )
            imported += 1
        self.campaign_repository.save(campaign)
        self.audit_log.append(campaign.id, "campaign.adoption_events_imported", {"imported": imported, "skipped": skipped})
        return {"imported": imported, "skipped": skipped}

    def build_report(self, campaign_id: str) -> dict:
        campaign, publication, review = self._context(campaign_id)
        interactions = [item for item in campaign.interactions if item.interaction_type.startswith("mautic.")]
        counts = Counter(item.interaction_type.removeprefix("mautic.") for item in interactions)
        sent = counts["sent"] or 1
        delivered = counts["delivered"] or counts["sent"]
        opened = counts["opened"]
        clicked = counts["clicked"]
        bounced = counts["bounced"]
        unsubscribed = counts["unsubscribed"]
        complaints = counts["complaint"]
        membership_ids = sorted(
            {
                membership_id
                for item in interactions
                for membership_id in item.metadata.get("membership_ids", [])
            }
        )
        reference_at = publication.scheduled_at or campaign.updated_at
        before = self.mapsi_usage_repository.usage_window_totals(
            membership_ids,
            start=reference_at - timedelta(days=30),
            end=reference_at,
        )
        after_7 = self.mapsi_usage_repository.usage_window_totals(membership_ids, start=reference_at, end=reference_at + timedelta(days=7))
        after_30 = self.mapsi_usage_repository.usage_window_totals(membership_ids, start=reference_at, end=reference_at + timedelta(days=30))
        activity_7 = self.mapsi_usage_repository.activity_summary(membership_ids, reference_at=reference_at, after_days=7)
        segment_progress = {
            "audience_segment_id": review.segment_id,
            "before_total_events": sum(before.values()),
            "after_7d_total_events": sum(after_7.values()),
            "after_30d_total_events": sum(after_30.values()),
            "delta_7d": sum(after_7.values()) - sum(before.values()),
            "delta_30d": sum(after_30.values()) - sum(before.values()),
        }
        rates = {
            "open_rate": opened / delivered if delivered else 0.0,
            "click_rate": clicked / delivered if delivered else 0.0,
            "unsubscribe_rate": unsubscribed / delivered if delivered else 0.0,
            "bounce_rate": bounced / sent if sent else 0.0,
            "complaint_rate": complaints / delivered if delivered else 0.0,
            "deliverability_rate": delivered / sent if sent else 0.0,
        }
        report = {
            "campaign_id": campaign.id,
            "asset_version": publication.content_version,
            "audience_segment_id": review.segment_id,
            "scheduled_at": reference_at.isoformat() if reference_at else None,
            "events": {
                "sent": counts["sent"],
                "delivered": counts["delivered"],
                "opened": opened,
                "clicked": clicked,
                "bounced": bounced,
                "unsubscribed": unsubscribed,
                "complaints": complaints,
            },
            "rates": rates,
            "usage": {
                "connected_in_7_days": activity_7["connected_after_window"],
                "feature_usage_before": sum(before.values()),
                "feature_usage_after_7_days": sum(after_7.values()),
                "feature_usage_after_30_days": sum(after_30.values()),
                "reactivated_users": activity_7["reactivated_users"],
            },
            "segment_progress": segment_progress,
            "alerts": self._alerts(rates, segment_progress, sent),
            "confidentiality": {"contains_contact_keys": False, "contains_emails": False},
            "limits": {
                "attribution": "Correlative only. Usage deltas may include parallel product, support or customer-side effects.",
            },
        }
        self.audit_log.append(campaign.id, "campaign.adoption_report_built", {"alerts": report["alerts"]})
        structured_log("campaign.adoption_report_built", campaign_id=campaign.id, alerts=len(report["alerts"]))
        return report

    def build_weekly_report(self) -> dict:
        campaigns = self.campaign_repository.list()
        eligible = [campaign for campaign in campaigns if any(item.channel == "mautic" for item in campaign.publications)]
        reports = [self.build_report(campaign.id) for campaign in eligible]
        return {
            "campaigns": len(reports),
            "alerts": sum(len(item["alerts"]) for item in reports),
            "reports": reports,
        }

    def _alerts(self, rates: dict, segment_progress: dict, sent: int) -> list[str]:
        alerts: list[str] = []
        if rates["unsubscribe_rate"] > self.settings.adoption_alert_unsubscribe_rate:
            alerts.append("high_unsubscribe_rate")
        if rates["bounce_rate"] > self.settings.adoption_alert_bounce_rate:
            alerts.append("high_bounce_rate")
        if rates["deliverability_rate"] < self.settings.adoption_alert_deliverability_floor:
            alerts.append("deliverability_drop")
        effect_rate = (segment_progress["delta_7d"] / sent) if sent else 0.0
        if effect_rate < self.settings.adoption_alert_effect_floor:
            alerts.append("absence_of_effect")
        error_rate = (rates["bounce_rate"] + rates["complaint_rate"])
        if error_rate > self.settings.adoption_alert_error_rate:
            alerts.append("abnormal_error_growth")
        return alerts

    def _context(self, campaign_id: str):
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            raise CampaignPublicationForbiddenError("Review bundle missing.")
        publication = self.mautic_publications.get(campaign_id, review.content_version, review.segment_version)
        if publication is None or not publication.mautic_campaign_id:
            raise CampaignPublicationForbiddenError("No Mautic publication found for this campaign version.")
        return campaign, publication, review

    def _parse_datetime(self, value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
