from __future__ import annotations

from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.domain.entities import Interaction, LinkedInPublication, Publication, utcnow
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, DuplicateCampaignPublicationError
from app.infrastructure.connectors.linkedin import LinkedInConnector
from app.infrastructure.observability import structured_log
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.linkedin import LinkedInPublicationRepository


class LinkedInPostPublisher:
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        publication_repository: LinkedInPublicationRepository,
        oauth_service: LinkedInOAuthService,
        organization_resolver: LinkedInOrganizationResolver,
        connector: LinkedInConnector,
        audit_log: SqlAlchemyAuditLogRepository,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.publication_repository = publication_repository
        self.oauth_service = oauth_service
        self.organization_resolver = organization_resolver
        self.connector = connector
        self.audit_log = audit_log

    def publish_asset(self, campaign_id: str, asset_id: str, *, idempotency_key: str = "") -> dict:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        if campaign.status not in {CampaignStatus.APPROVED, CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}:
            raise CampaignPublicationForbiddenError("Campaign must be APPROVED before LinkedIn publication.")
        asset = next((item for item in campaign.content_assets if item.id == asset_id), None)
        if asset is None:
            raise CampaignPublicationForbiddenError("LinkedIn asset not found.")
        if asset.channel != "linkedin":
            raise CampaignPublicationForbiddenError("Asset is not a LinkedIn asset.")
        existing = self.publication_repository.get_by_asset_hash(asset.id, asset.content_hash)
        if existing and existing.status in {"published", "manual_copy"}:
            if idempotency_key and existing.idempotency_key and existing.idempotency_key != idempotency_key:
                raise DuplicateCampaignPublicationError("This LinkedIn asset version has already been published.")
            return self._serialize(existing)
        if asset.status is not AssetStatus.APPROVED:
            raise CampaignPublicationForbiddenError("LinkedIn publication requires an APPROVED asset.")

        publication = existing or LinkedInPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            content_hash=asset.content_hash,
            asset_type=asset.asset_type,
            mode=self.connector.config.mode,
            idempotency_key=idempotency_key,
        )
        if asset.asset_type == "linkedin_personal_draft":
            publication.status = "manual_copy"
            publication.mode = "manual"
            publication.last_error = ""
            publication.published_at = utcnow()
            publication.metrics = {"manual_copy_required": True}
            publication = self.publication_repository.save(publication)
            self.audit_log.append(campaign.id, "campaign.linkedin_manual_copy_required", {"asset_id": asset.id})
            return self._serialize(publication)

        token = self.oauth_service.get_valid_token()
        self.connector.config.access_token = token.access_token
        organization = self.organization_resolver.resolve()
        remote = self.connector.create_post(author_urn=organization["urn"], commentary=asset.body)

        publication.organization_urn = organization["urn"]
        publication.linkedin_post_urn = remote["post_urn"]
        publication.status = "published"
        publication.mode = self.connector.config.mode
        publication.idempotency_key = idempotency_key
        publication.last_error = ""
        publication.published_at = utcnow()
        publication.metrics = {"post_urn": remote["post_urn"]}
        publication = self.publication_repository.save(publication)

        asset.results = {**asset.results, "linkedin_post_urn": remote["post_urn"]}
        campaign.publish(
            Publication(
                campaign_run_id=campaign.id,
                content_asset_id=asset.id,
                channel="linkedin",
                external_reference=remote["post_urn"],
                external_url=remote["post_urn"],
            )
        )
        campaign.interactions.append(
            Interaction(
                campaign_run_id=campaign.id,
                interaction_type="linkedin_post_published",
                metadata={"asset_id": asset.id, "post_urn": remote["post_urn"], "mode": self.connector.config.mode},
            )
        )
        self.campaign_repository.save(campaign)
        self.audit_log.append(campaign.id, "campaign.linkedin_published", {"asset_id": asset.id, "post_urn": remote["post_urn"]})
        structured_log("campaign.linkedin_published", campaign_id=campaign.id, asset_id=asset.id, mode=self.connector.config.mode)
        return self._serialize(publication)

    def _serialize(self, publication: LinkedInPublication) -> dict:
        return {
            "campaign_id": publication.campaign_run_id,
            "content_asset_id": publication.content_asset_id,
            "content_hash": publication.content_hash,
            "asset_type": publication.asset_type,
            "organization_urn": publication.organization_urn,
            "linkedin_post_urn": publication.linkedin_post_urn,
            "status": publication.status,
            "mode": publication.mode,
            "metrics": publication.metrics,
            "published_at": publication.published_at.isoformat() if publication.published_at else None,
        }
