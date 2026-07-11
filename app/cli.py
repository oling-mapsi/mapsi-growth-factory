from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.editorial_agents import (
    CustomerEmailWriterAgent,
    EditorialStrategyAgent,
    LinkedInWriterAgent,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    ProductIntelligenceAgent,
    QualityControlAgent,
    SeoQualityAgent,
    UsageIntelligenceAgent,
    WebsiteArticleWriterAgent,
)
from app.application.services.mapsi_usage_collection_service import MapsiUsageCollectionService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.multichannel_content_service import MultichannelContentService
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.application.services.weekly_campaign_generation_service import WeeklyCampaignGenerationService
from app.core.config import get_mapsi_instances, get_settings
from app.core.db import Base, SessionLocal, engine
from app.infrastructure.agents.openai_backend import OpenAIAgentsBackend
from app.infrastructure.agents.simulated_backend import SimulatedEditorialBackend
from app.infrastructure.connectors.mautic import MauticConnector, build_mautic_config
from app.infrastructure.connectors.mapsi_usage import MapsiInstanceConfig, MapsiUsageConnector
from app.infrastructure.connectors.oling import OlingConnector, build_oling_config
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.db.models import ContentAssetModel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mapsi-growth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect-mapsi-usage")
    collect.add_argument("--instance", required=True)
    collect.add_argument("--dry-run", action="store_true")
    preview = subparsers.add_parser("preview-audience-segment")
    preview.add_argument("--segment")
    preview.add_argument("--rule-file")
    preview.add_argument("--allow-disabled", action="store_true")
    preview.add_argument("--dry-run", action="store_true")
    provision = subparsers.add_parser("provision-mautic")
    provision.add_argument("--dry-run", action="store_true")
    sync = subparsers.add_parser("sync-mautic-contacts")
    sync.add_argument("--dry-run", action="store_true")
    weekly = subparsers.add_parser("generate-weekly-campaign")
    weekly.add_argument("--dry-run", action="store_true")
    multichannel = subparsers.add_parser("generate-market-assets")
    multichannel.add_argument("--campaign-id", required=True)
    multichannel.add_argument("--dry-run", action="store_true")
    multichannel.add_argument("--authorized-client", action="append", default=[])
    publish_asset = subparsers.add_parser("publish-asset")
    publish_asset.add_argument("--asset-id", required=True)
    publish_asset.add_argument("--channel", required=True, choices=["oling"])
    publish_asset.add_argument("--dry-run", action="store_true")
    return parser


def load_instance_config(instance_key: str) -> MapsiInstanceConfig:
    for item in get_mapsi_instances():
        if item["id"] == instance_key:
            return MapsiInstanceConfig(
                id=item["id"],
                base_url=item["base_url"],
                secret_ref=item["secret_ref"],
                enabled=bool(item["enabled"]),
            )
    raise SystemExit(f"Unknown MAPSI instance: {instance_key}")


def build_editorial_backend():
    if get_settings().editorial_agent_backend == "openai":
        return OpenAIAgentsBackend()
    return SimulatedEditorialBackend()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "collect-mapsi-usage":
        instance = load_instance_config(args.instance)
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            service = MapsiUsageCollectionService(
                connector=MapsiUsageConnector(instance),
                repository=MapsiUsageRepository(session),
                instance_config=instance,
            )
            report = service.collect(dry_run=args.dry_run)
            print(report)
        return 0
    if args.command == "preview-audience-segment":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            service = AudienceSegmentationService(AudienceSegmentationRepository(session))
            if args.rule_file:
                payload = json.loads(Path(args.rule_file).read_text(encoding="utf-8"))
                preview = service.preview_proposed_segment(payload, persist=not args.dry_run)
            elif args.segment:
                preview = service.preview_segment(args.segment, persist=not args.dry_run, allow_disabled=args.allow_disabled)
            else:
                raise SystemExit("Either --segment or --rule-file is required.")
            print(
                json.dumps(
                    {
                        "segment_id": preview.segment_id,
                        "status": preview.status,
                        "blocked_reasons": preview.blocked_reasons,
                        "total_volume": preview.total_volume,
                        "eligible_volume": preview.eligible_volume,
                        "exclusions_by_reason": preview.exclusions_by_reason,
                        "role_distribution": preview.role_distribution,
                        "module_distribution": preview.module_distribution,
                        "client_distribution": preview.client_distribution,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.command in {"provision-mautic", "sync-mautic-contacts"}:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            segmentation = AudienceSegmentationService(AudienceSegmentationRepository(session))
            service = MauticContactSyncService(
                connector=MauticConnector(build_mautic_config()),
                repository=MauticSyncRepository(session),
                segmentation_service=segmentation,
            )
            if args.command == "provision-mautic":
                print(json.dumps(service.provision(dry_run=args.dry_run), indent=2, sort_keys=True))
            else:
                print(json.dumps(service.sync_contacts(dry_run=args.dry_run), indent=2, sort_keys=True))
        return 0
    if args.command == "generate-weekly-campaign":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            backend = build_editorial_backend()
            service = WeeklyCampaignGenerationService(
                product_agent=ProductIntelligenceAgent(backend),
                usage_agent=UsageIntelligenceAgent(backend),
                strategy_agent=EditorialStrategyAgent(backend),
                writer_agent=CustomerEmailWriterAgent(backend),
                quality_agent=QualityControlAgent(backend),
                segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
                repository=EditorialPipelineRepository(session),
            )
            print(json.dumps(service.generate(dry_run=args.dry_run), indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "generate-market-assets":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            backend = build_editorial_backend()
            repository = SqlAlchemyCampaignRepository(session)
            audit_log = SqlAlchemyAuditLogRepository(session)
            service = MultichannelContentService(
                repository=repository,
                review_portal=ReviewPortalService(repository, ReviewPortalRepository(session), audit_log),
                market_strategy_agent=MarketEditorialStrategyAgent(backend),
                newsletter_writer=NewsletterWriterAgent(backend),
                linkedin_writer=LinkedInWriterAgent(backend),
                website_writer=WebsiteArticleWriterAgent(backend),
                seo_quality_agent=SeoQualityAgent(backend),
            )
            print(
                json.dumps(
                    service.generate(
                        args.campaign_id,
                        dry_run=args.dry_run,
                        authorized_client_mentions=args.authorized_client,
                    ),
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
        return 0
    if args.command == "publish-asset":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            row = session.query(ContentAssetModel.campaign_run_id).filter(ContentAssetModel.id == args.asset_id).one_or_none()
            if row is None:
                raise SystemExit(f"Unknown asset: {args.asset_id}")
            repository = SqlAlchemyCampaignRepository(session)
            audit_log = SqlAlchemyAuditLogRepository(session)
            review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
            if args.channel != "oling":
                raise SystemExit(f"Unsupported channel: {args.channel}")
            service = OlingNewsPublisher(
                campaign_repository=repository,
                publication_repository=OlingNewsPublicationRepository(session),
                connector=OlingConnector(build_oling_config()),
                audit_log=audit_log,
                review_portal=review_portal,
            )
            print(
                json.dumps(
                    service.publish_asset(row[0], args.asset_id, dry_run=args.dry_run),
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
