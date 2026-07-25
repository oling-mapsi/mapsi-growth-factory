from __future__ import annotations

import json

from app.application.models.editorial_agents import (
    CustomerEmailWriterInput,
    EditorialConsumptionSummary,
    EditorialEvaluationResult,
    EvidenceReference,
    LinkedInWriterInput,
    MarketEditorialStrategyInput,
    NewsletterWriterInput,
    SeoQualityInput,
    WebsiteArticleWriterInput,
)
from app.application.services.editorial_agents import (
    detect_editorial_policy_violations,
    LinkedInWriterAgent,
    MapsiArticleWriter,
    MapsiStudioContentWriter,
    MapsiUserEmailWriter,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    OlingArticleWriter,
    SeoQualityAgent,
    WebsiteArticleWriterAgent,
    contains_pii,
)
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.core.security import sha256_hexdigest
from app.domain.entities import ContentAsset
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignNotFoundError, EditorialGenerationBlockedError
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository


CHANNEL_MAP = {
    "customer_email": "mautic",
    "mapsi_user_email": "mapsi_users",
    "prospect_newsletter": "prospect_newsletter",
    "linkedin_company_post": "linkedin",
    "linkedin_personal_draft": "linkedin",
    "website_article": "oling",
    "oling_news_article": "oling",
    "mapsi_news_article": "mapsi_site",
    "mapsi_studio_news": "mapsi_studio",
    "mapsi_studio_tip": "mapsi_studio",
    "website_cta": "oling",
    "demonstration_landing_page": "oling",
    "demonstration_call_to_action": "oling",
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
        mapsi_user_email_writer: MapsiUserEmailWriter,
        oling_writer: OlingArticleWriter,
        mapsi_writer: MapsiArticleWriter,
        mapsi_studio_writer: MapsiStudioContentWriter,
        seo_quality_agent: SeoQualityAgent,
    ) -> None:
        self.repository = repository
        self.review_portal = review_portal
        self.market_strategy_agent = market_strategy_agent
        self.newsletter_writer = newsletter_writer
        self.linkedin_writer = linkedin_writer
        self.website_writer = website_writer
        self.mapsi_user_email_writer = mapsi_user_email_writer
        self.oling_writer = oling_writer
        self.mapsi_writer = mapsi_writer
        self.mapsi_studio_writer = mapsi_studio_writer
        self.seo_quality_agent = seo_quality_agent
        self.max_budget_tokens = get_settings().editorial_generation_max_budget_tokens
        self._consumed_tokens = 0

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
        self._track(self.market_strategy_agent)
        generated_assets: list[ContentAsset] = []
        evaluations: list[dict] = []
        for plan in strategy.plans:
            self._validate_plan(plan, evidence_index, authorized_client_mentions or [])
            cta_label = ""
            cta_url = ""
            if plan.asset_type == "mapsi_user_email":
                output = self.mapsi_user_email_writer.run(
                    CustomerEmailWriterInput(
                        topic=plan.title,
                        objective=plan.angle,
                        audience_segment_id=plan.audience_segment_id,
                        key_messages=[benefit.statement for benefit in plan.benefits],
                        cta_type="read_guide",
                        evidences=self._evidences(plan.evidence_ids, evidence_index),
                    )
                )
                self._track(self.mapsi_user_email_writer)
                body = output.body_html
                title = output.subject
                evidence_ids = output.evidence_ids
                cta_label = output.cta_label
                cta_url = output.cta_url_template
            elif plan.asset_type == "prospect_newsletter":
                output = self.newsletter_writer.run(NewsletterWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                self._track(self.newsletter_writer)
                body = output.body_html
                title = output.subject
                evidence_ids = output.evidence_ids
                cta_label = output.cta_label
                cta_url = output.cta_url_template
            elif plan.asset_type in {"linkedin_company_post", "linkedin_personal_draft"}:
                output = self.linkedin_writer.run(LinkedInWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                self._track(self.linkedin_writer)
                body = output.post_text
                title = output.hook
                evidence_ids = output.evidence_ids
                cta_label = output.cta_label
                cta_url = output.cta_url_template
            elif plan.asset_type in {"website_article", "oling_news_article", "mapsi_news_article", "mapsi_studio_news", "mapsi_studio_tip"}:
                writer = self._resolve_article_writer(plan.asset_type)
                output = writer.run(WebsiteArticleWriterInput(plan=plan, evidences=self._evidences(plan.evidence_ids, evidence_index)))
                self._track(writer)
                seo = self.seo_quality_agent.run(
                    SeoQualityInput(
                        article=output,
                        evidences=self._evidences(plan.evidence_ids, evidence_index),
                        allowed_client_mentions=authorized_client_mentions or [],
                    )
                )
                self._track(self.seo_quality_agent)
                if not seo.passed:
                    raise EditorialGenerationBlockedError(f"SEO quality failed: {[issue.code for issue in seo.issues]}")
                body = output.body_html
                title = output.headline
                evidence_ids = output.evidence_ids
                cta_label = output.cta_label
                cta_url = output.cta_url_template
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
                locale="fr-FR",
                title=title,
                subject=title if plan.asset_type in {"mapsi_user_email", "prospect_newsletter", "customer_email"} else "",
                content_html=body if body.startswith("<") else None,
                content_text=body if not body.startswith("<") else self._plain_text(body),
                excerpt=self._excerpt(body),
                call_to_action=cta_label,
                target_url=cta_url,
                source_evidence_ids=evidence_ids,
                audience_segment_id=plan.audience_segment_id,
                status=AssetStatus.READY_FOR_REVIEW,
                content_hash=self._content_hash(plan.asset_type, title, body, evidence_ids, plan.audience_segment_id),
                results={},
            )
            generated_assets.append(asset)
            evaluations.append(
                self._evaluation_for_asset(plan.asset_type, title, body, evidence_ids, evidence_index, authorized_client_mentions or [], plan.client_mentions)
            )
        if any(item["contains_pii"] for item in evaluations if "contains_pii" in item):
            raise EditorialGenerationBlockedError("Generated market content contains personal data.")
        violations = [code for item in evaluations for code in item.get("policy_violations", [])]
        if violations:
            raise EditorialGenerationBlockedError(f"Editorial policy failed: {sorted(set(violations))}")
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
            "engine": {
                "mode": self._engine_mode(),
                "consumption": self._consumption().model_dump(mode="json"),
            },
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

    def _resolve_article_writer(self, asset_type: str):
        if asset_type == "mapsi_news_article":
            return self.mapsi_writer
        if asset_type in {"mapsi_studio_news", "mapsi_studio_tip"}:
            return self.mapsi_studio_writer
        if asset_type in {"oling_news_article", "website_article"}:
            return self.oling_writer
        return self.website_writer

    def _track(self, agent) -> None:
        metadata = agent.last_execution
        if metadata is None:
            raise EditorialGenerationBlockedError("Missing editorial execution metadata.")
        self._consumed_tokens += metadata.token_usage.total_tokens
        if self._consumed_tokens > self.max_budget_tokens:
            raise EditorialGenerationBlockedError("Editorial generation budget exceeded.")

    def _evaluation_for_asset(
        self,
        asset_type: str,
        title: str,
        body: str,
        evidence_ids: list[str],
        evidence_index: dict[str, EvidenceReference],
        authorized_client_mentions: list[str],
        client_mentions: list[str],
    ) -> dict:
        policy_violations = detect_editorial_policy_violations({"title": title, "body": body})
        evaluations = [
            EditorialEvaluationResult(name="valid_evidence", passed=set(evidence_ids).issubset(evidence_index.keys())),
            EditorialEvaluationResult(name="absence_of_personal_data", passed=not contains_pii({"title": title, "body": body})),
            EditorialEvaluationResult(name="authorized_client_mentions", passed=all(client in authorized_client_mentions for client in client_mentions)),
            EditorialEvaluationResult(name="policy_compliance", passed=not policy_violations, details={"violations": policy_violations}),
        ]
        payload = {"asset_type": asset_type}
        for item in evaluations:
            payload[item.name] = item.passed
            if item.name == "absence_of_personal_data":
                payload["contains_pii"] = not item.passed
        payload["policy_violations"] = policy_violations
        return payload

    def _content_hash(self, asset_type: str, title: str, body: str, evidence_ids: list[str], audience_segment_id: str) -> str:
        return sha256_hexdigest(
            json.dumps(
                {
                    "asset_type": asset_type,
                    "locale": "fr-FR",
                    "title": title,
                    "subject": title if asset_type in {"mapsi_user_email", "prospect_newsletter", "customer_email"} else "",
                    "content_html": body if body.startswith("<") else "",
                    "content_text": body if not body.startswith("<") else self._plain_text(body),
                    "excerpt": self._excerpt(body),
                    "call_to_action": "",
                    "target_url": "",
                    "evidence_ids": evidence_ids,
                    "audience_segment_id": audience_segment_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def _plain_text(self, value: str) -> str:
        return " ".join(value.replace("</p>", " ").replace("<p>", " ").replace("<br>", " ").replace("<br />", " ").split())

    def _excerpt(self, value: str, max_length: int = 160) -> str:
        plain = self._plain_text(value)
        if len(plain) <= max_length:
            return plain
        return plain[: max_length - 3].rstrip() + "..."

    def _consumption(self) -> EditorialConsumptionSummary:
        remaining = max(0, self.max_budget_tokens - self._consumed_tokens)
        return EditorialConsumptionSummary(
            budget_tokens=self.max_budget_tokens,
            used_tokens=self._consumed_tokens,
            remaining_tokens=remaining,
            mode=self._engine_mode(),
        )

    def _engine_mode(self) -> str:
        provider_type = getattr(self.market_strategy_agent.last_execution, "provider_type", "")
        return "real" if provider_type == "openai" else "simulated"
