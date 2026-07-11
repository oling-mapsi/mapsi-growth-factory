from __future__ import annotations

from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.domain.entities import Interaction, utcnow
from app.domain.errors import CampaignNotFoundError
from app.infrastructure.connectors.linkedin import LinkedInConnector
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.linkedin import LinkedInPublicationRepository


class LinkedInMetricsCollector:
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        publication_repository: LinkedInPublicationRepository,
        oauth_service: LinkedInOAuthService,
        connector: LinkedInConnector,
        audit_log: SqlAlchemyAuditLogRepository,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.publication_repository = publication_repository
        self.oauth_service = oauth_service
        self.connector = connector
        self.audit_log = audit_log

    def collect(self, campaign_id: str) -> dict:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        token = self.oauth_service.get_valid_token()
        self.connector.config.access_token = token.access_token
        publications = self.publication_repository.list_by_campaign(campaign_id)
        collected = 0
        assets_by_id = {asset.id: asset for asset in campaign.content_assets}
        for publication in publications:
            if publication.status != "published" or not publication.linkedin_post_urn:
                continue
            metrics = self.connector.get_post_metrics(publication.linkedin_post_urn)
            publication.metrics = metrics
            publication.metrics_collected_at = utcnow()
            publication.last_error = ""
            self.publication_repository.save(publication)
            asset = assets_by_id.get(publication.content_asset_id)
            if asset is not None:
                asset.results = {**asset.results, "linkedin_metrics": metrics}
            campaign.interactions.append(
                Interaction(
                    campaign_run_id=campaign.id,
                    interaction_type="linkedin_metrics_collected",
                    metadata={"asset_id": publication.content_asset_id, **metrics},
                )
            )
            collected += 1
        self.campaign_repository.save(campaign)
        self.audit_log.append(campaign.id, "campaign.linkedin_metrics_collected", {"count": collected})
        return {"campaign_id": campaign.id, "collected": collected}
