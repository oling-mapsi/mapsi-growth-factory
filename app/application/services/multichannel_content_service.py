from __future__ import annotations

import json

from app.application.models.editorial_agents import (
    EvidenceReference,
    LinkedInWriterInput,
    MarketEditorialStrategyInput,
    NewsletterWriterInput,
    SeoQualityInput,
    WebsiteArticleWriterInput,
)
from app.application.services.editorial_agents import (
    LinkedInWriterAgent,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    SeoQualityAgent,
    WebsiteArticleWriterAgent,
    contains_pii,
)
from app.application.services.review_portal_service import ReviewPortalService
from app.core.security import sha256_hexdigest
from app.domain.entities import ContentAsset
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignNotFoundError, EditorialGenerationBlockedError
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


CHANNEL_MAP = {
    "customer_email": "mautic",
    "prospect_newsletter": "mautic",
    "linkedin_company_post": "linkedin",
    "linkedin_personal_draft": "linkedin",
    "website_article": "oling",
    "website_cta": "oling",
    "demonstration_landing_page": "oling",
}


class MultichannelContentService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyCampaignRepository,
        review_portal: ReviewPortalService,
        market_strategy_agent: MarketEditorialStrategyAgent,
        newsletter_writer: NewsletterWriterAgent,
        linkedin_writer: LinkedInWriterAgent,
        website_writer: WebsiteArticleWriterAgent,
        seo_quality_agent: SeoQualityAgent,
    ) -> None:
        self.repository = repository
        self.review_portal = review_portal
        self.market_strategy_agent = market_strategy_agent
        self.newsletter_writer = newsletter_writer
        self.linkedin_writer = linkedin_writer
        self.website_writer = website_writer
        self.seo_quality_agent = seo_quality_agent

    def generate(self, campaign_id: str, *, dry_run: bool = True, authorized_client_mentions: list[str] | None = None) -> dict:
        campaign = self.repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        if campaign.status is not CampaignStatus.APPROVED:
            raise EditorialGenerationBlockedError("Campaign must be APPROVED before multichannel generation.")
        review = self.review_portal.review_repository.get_review_by_campaign(campaign_id)
        if review is None or review.approved_at is None:
            raise EditorialGenerationBlockedError("Campaign review must be approved before multichannel generation.")
        evidence_index = {
            evidence.id: EvidenceReference(
                evidence_id=evidence.id,
                source_system=evidence.source_system,
                reference=evidence.reference,
                summary=evidence.reference,
                deployed=True,
                client_scope="global",
            )
            for evidence in campaign.source_evidences
        }
        strategy = self.market_strategy_agent.run(
            MarketEditorialStrategyInput(
                topic=review.theme,
                objective=review.objective,
                audience_segment_id=review.segment_id,
                evidences=list(evidence_index.values()),
                authorized_client_mentions=authorized_client_mentions or [],
            )
        )
        generated_assets: list[ContentAsset] = []
        evaluations: list[dict] = []
        for plan in strategy.plans:
            self._validate_plan(plan, evidence_index, authorized_client_mentions or [])
            if plan.asset_type == "prospect_newsletter":
                output = self.newsletter_writer.run(NewsletterWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                body = output.body_html
                title = output.subject
                evidence_ids = output.evidence_ids
            elif plan.asset_type in {"linkedin_company_post", "linkedin_personal_draft"}:
                output = self.linkedin_writer.run(LinkedInWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                body = output.post_text
                title = output.hook
                evidence_ids = output.evidence_ids
            elif plan.asset_type == "website_article":
                output = self.website_writer.run(WebsiteArticleWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                seo = self.seo_quality_agent.run(
                    SeoQualityInput(
                        article=output,
                        evidences=self._evidences(plan.evidence_ids, evidence_index),
                        allowed_client_mentions=authorized_client_mentions or [],
                    )
                )
                if not seo.passed:
                    raise EditorialGenerationBlockedError(f"SEO quality failed: {[issue.code for issue in seo.issues]}")
                body = output.body_html
                title = output.headline
                evidence_ids = output.evidence_ids
                evaluations.append({"asset_type": plan.asset_type, "seo_passed": seo.passed, "issues": [issue.code for issue in seo.issues]})
            else:
                body = json.dumps(
                    {
                        "title": plan.title,
                        "angle": plan.angle,
                        "benefits": [benefit.model_dump(mode="json") for benefit in plan.benefits],
                    },
                    sort_keys=True,
                )
                title = plan.title
                evidence_ids = list(plan.evidence_ids)
            asset = ContentAsset(
                campaign_run_id=campaign.id,
                asset_type=plan.asset_type,
                channel=CHANNEL_MAP[plan.asset_type],
                title=title,
                body=body,
                evidence_ids=evidence_ids,
                audience_segment_id=plan.audience_segment_id,
                status=AssetStatus.READY_FOR_REVIEW,
                content_hash=self._content_hash(plan.asset_type, title, body, evidence_ids, plan.audience_segment_id),
                results={},
            )
            generated_assets.append(asset)
            evaluations.append(
                {
                    "asset_type": plan.asset_type,
                    "has_valid_evidence": set(evidence_ids).issubset(evidence_index.keys()),
                    "contains_pii": contains_pii({"title": title, "body": body}),
                    "authorized_client_mentions": all(client in (authorized_client_mentions or []) for client in plan.client_mentions),
                }
            )
        if any(item["contains_pii"] for item in evaluations if "contains_pii" in item):
            raise EditorialGenerationBlockedError("Generated market content contains personal data.")
        if not dry_run:
            campaign.content_assets.extend(generated_assets)
            self.repository.save(campaign)
        incr("editorial.multichannel.generated", len(generated_assets))
        structured_log("editorial.multichannel.generated", campaign_id=campaign.id, assets=len(generated_assets), dry_run=dry_run)
        return {
            "campaign_id": campaign.id,
            "asset_count": len(generated_assets),
            "assets": [
                {
                    "asset_type": asset.asset_type,
                    "channel": asset.channel,
                    "title": asset.title,
                    "audience_segment_id": asset.audience_segment_id,
                    "evidence_ids": asset.evidence_ids,
                    "status": asset.status.value,
                    "content_hash": asset.content_hash,
                }
                for asset in generated_assets
            ],
            "evaluations": evaluations,
        }

    def _validate_plan(self, plan, evidence_index: dict[str, EvidenceReference], authorized_client_mentions: list[str]) -> None:
        if not plan.evidence_ids or any(evidence_id not in evidence_index for evidence_id in plan.evidence_ids):
            raise EditorialGenerationBlockedError("Market plan contains unsupported evidence ids.")
        if any(client not in authorized_client_mentions for client in plan.client_mentions):
            raise EditorialGenerationBlockedError("Market plan mentions an unauthorized client.")
        for benefit in plan.benefits:
            if not benefit.evidence_ids or any(evidence_id not in evidence_index for evidence_id in benefit.evidence_ids):
                raise EditorialGenerationBlockedError("Benefit claim is missing valid evidence.")

    def _evidences(self, evidence_ids: list[str], index: dict[str, EvidenceReference]) -> list[EvidenceReference]:
        return [index[evidence_id] for evidence_id in evidence_ids]

    def _content_hash(self, asset_type: str, title: str, body: str, evidence_ids: list[str], audience_segment_id: str) -> str:
        return sha256_hexdigest(
            json.dumps(
                {
                    "asset_type": asset_type,
                    "title": title,
                    "body": body,
                    "evidence_ids": evidence_ids,
                    "audience_segment_id": audience_segment_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
