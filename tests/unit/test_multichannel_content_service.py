from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.services.editorial_agents import (
    LinkedInWriterAgent,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    SeoQualityAgent,
    WebsiteArticleWriterAgent,
)
from app.application.services.multichannel_content_service import MultichannelContentService
from app.application.services.review_portal_service import ReviewPortalService
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.agents.fake_backend import FakeStructuredAgentBackend
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository


def seed_campaign(session) -> str:
    campaign = CampaignRun(
        name="Validated campaign",
        objective="feature_adoption",
        status=CampaignStatus.APPROVED,
        content_assets=[
            ContentAsset(
                campaign_run_id="",
                asset_type="customer_email",
                channel="mautic",
                title="Subject",
                body="<p>Body</p>",
                status=AssetStatus.APPROVED,
            )
        ],
        audience_segments=[AudienceSegment(name="All eligible", description="All eligible users")],
        source_evidences=[SourceEvidence(source_system="github", reference="sha:123", evidence_type="deployment_proof")],
    )
    for asset in campaign.content_assets:
        asset.campaign_run_id = campaign.id
    for segment in campaign.audience_segments:
        segment.campaign_run_id = campaign.id
    for evidence in campaign.source_evidences:
        evidence.campaign_run_id = campaign.id
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_repository = ReviewPortalRepository(session)
    review_service = ReviewPortalService(repository, review_repository, audit_log)
    repository.add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        theme=campaign.name,
        objective=campaign.objective,
        segment_id="all_eligible_active_users",
        segment_label="All eligible active users",
        segment_version=1,
        audience_volume=12,
        exclusions={},
        evidence_ids=[campaign.source_evidences[0].id],
        email_subject="Subject",
        email_preheader="Preheader",
        email_html="<p>Body</p>",
        email_text="Body",
        quality_control={"passed": True},
        approved_by="admin",
        approved_at=datetime.now(UTC),
    )
    review.approved_content_hash = review_service.content_hash(review)
    review.approved_audience_hash = review_service.audience_hash(review)
    review_repository.save_review(review)
    return campaign.id


def build_service(session, responses) -> MultichannelContentService:
    backend = FakeStructuredAgentBackend(responses)
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    return MultichannelContentService(
        repository=repository,
        review_portal=ReviewPortalService(repository, ReviewPortalRepository(session), audit_log),
        market_strategy_agent=MarketEditorialStrategyAgent(backend),
        newsletter_writer=NewsletterWriterAgent(backend),
        linkedin_writer=LinkedInWriterAgent(backend),
        website_writer=WebsiteArticleWriterAgent(backend),
        seo_quality_agent=SeoQualityAgent(backend),
    )


def test_generate_multichannel_assets_persists_supported_types(session) -> None:
    campaign_id = seed_campaign(session)
    evidence_id = SqlAlchemyCampaignRepository(session).get(campaign_id).source_evidences[0].id
    service = build_service(
        session,
        [
            {
                "plans": [
                    {
                        "asset_type": "prospect_newsletter",
                        "title": "Newsletter title",
                        "angle": "Angle",
                        "audience_segment_id": "all_eligible_active_users",
                        "evidence_ids": [evidence_id],
                        "benefits": [{"statement": "Benefit demo", "claim_type": "demonstrated", "evidence_ids": [evidence_id]}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "linkedin_company_post",
                        "title": "LinkedIn title",
                        "angle": "Angle",
                        "audience_segment_id": "all_eligible_active_users",
                        "evidence_ids": [evidence_id],
                        "benefits": [{"statement": "Benefit expected", "claim_type": "expected", "evidence_ids": [evidence_id]}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "website_article",
                        "title": "Article title",
                        "angle": "Angle",
                        "audience_segment_id": "all_eligible_active_users",
                        "evidence_ids": [evidence_id],
                        "benefits": [{"statement": "Benefit demo", "claim_type": "demonstrated", "evidence_ids": [evidence_id]}],
                        "client_mentions": [],
                    },
                ]
            },
            {
                "subject": "Newsletter title",
                "preheader": "Preheader",
                "body_html": "<p>Newsletter</p>",
                "body_text": "Newsletter",
                "cta_label": "Demo",
                "cta_url_template": "https://oling.example/demo",
                "evidence_ids": [evidence_id],
            },
            {
                "post_text": "LinkedIn body",
                "hook": "LinkedIn title",
                "cta_label": "Read",
                "cta_url_template": "https://oling.example/article",
                "evidence_ids": [evidence_id],
            },
            {
                "headline": "Article title",
                "summary": "Summary",
                "body_html": "<p>Article</p>",
                "body_text": "Article",
                "seo_title": "SEO title",
                "meta_description": "Meta",
                "cta_label": "Demo",
                "cta_url_template": "https://oling.example/demo",
                "evidence_ids": [evidence_id],
            },
            {"passed": True, "issues": []},
        ],
    )

    report = service.generate(campaign_id, dry_run=False)
    persisted = SqlAlchemyCampaignRepository(session).get(campaign_id)

    assert report["asset_count"] == 3
    assert {item["asset_type"] for item in report["assets"]} == {"prospect_newsletter", "linkedin_company_post", "website_article"}
    assert len(persisted.content_assets) == 4
    assert all(asset.content_hash for asset in persisted.content_assets)
    assert all(asset.status in {AssetStatus.APPROVED, AssetStatus.READY_FOR_REVIEW} for asset in persisted.content_assets)


def test_generate_multichannel_blocks_unauthorized_client_mention(session) -> None:
    campaign_id = seed_campaign(session)
    evidence_id = SqlAlchemyCampaignRepository(session).get(campaign_id).source_evidences[0].id
    service = build_service(
        session,
        [
            {
                "plans": [
                    {
                        "asset_type": "prospect_newsletter",
                        "title": "Newsletter title",
                        "angle": "Angle",
                        "audience_segment_id": "all_eligible_active_users",
                        "evidence_ids": [evidence_id],
                        "benefits": [{"statement": "Benefit demo", "claim_type": "demonstrated", "evidence_ids": [evidence_id]}],
                        "client_mentions": ["Client X"],
                    }
                ]
            }
        ],
    )

    with pytest.raises(EditorialGenerationBlockedError, match="unauthorized client"):
        service.generate(campaign_id, dry_run=True, authorized_client_mentions=[])


def test_generate_multichannel_blocks_missing_evidence(session) -> None:
    campaign_id = seed_campaign(session)
    service = build_service(
        session,
        [
            {
                "plans": [
                    {
                        "asset_type": "website_article",
                        "title": "Article title",
                        "angle": "Angle",
                        "audience_segment_id": "all_eligible_active_users",
                        "evidence_ids": ["missing-evidence"],
                        "benefits": [{"statement": "Benefit demo", "claim_type": "demonstrated", "evidence_ids": ["missing-evidence"]}],
                        "client_mentions": [],
                    }
                ]
            }
        ],
    )

    with pytest.raises(EditorialGenerationBlockedError, match="unsupported evidence"):
        service.generate(campaign_id, dry_run=True)
