from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.editorial_agents import (
    CustomerEmailWriterAgent,
    EditorialStrategyAgent,
    LinkedInWriterAgent,
    MapsiArticleWriter,
    MapsiStudioContentWriter,
    MapsiUserEmailWriter,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    OlingArticleWriter,
    ProductIntelligenceAgent,
    QualityControlAgent,
    SeoQualityAgent,
    UsageIntelligenceAgent,
    WebsiteArticleWriterAgent,
)
from app.application.services.mapsi_usage_collection_service import MapsiUsageCollectionService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.multichannel_content_service import MultichannelContentService
from app.application.services.mapsi_news_publisher import MapsiNewsPublisher
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.application.services.weekly_campaign_generation_service import WeeklyCampaignGenerationService
from app.core.config import get_mapsi_instances, get_settings
from app.core.db import Base, SessionLocal, engine
from app.entrypoints.api.dependencies import get_studio_admin_service
from app.infrastructure.agents.openai_backend import OpenAIAgentsBackend
from app.infrastructure.agents.simulated_backend import SimulatedEditorialBackend
from app.infrastructure.connectors.mautic import MauticConnector, build_mautic_config
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors.mapsi_site_contract import get_openapi_info, get_request_example, supports_unpublish
from app.infrastructure.connectors.mapsi_usage import MapsiInstanceConfig, MapsiUsageConnector
from app.infrastructure.connectors.oling import OlingConnector, build_oling_config
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.db.models import AuditLogModel, ContentAssetModel


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
    weekly.add_argument("--mode", choices=["simulated", "real"])
    multichannel = subparsers.add_parser("generate-market-assets")
    multichannel.add_argument("--campaign-id", required=True)
    multichannel.add_argument("--dry-run", action="store_true")
    multichannel.add_argument("--authorized-client", action="append", default=[])
    multichannel.add_argument("--mode", choices=["simulated", "real"])
    generate_campaign = subparsers.add_parser("generate-campaign")
    generate_campaign.add_argument("--dry-run", action="store_true")
    generate_campaign.add_argument("--mode", choices=["simulated", "real"], default="simulated")
    publish_asset = subparsers.add_parser("publish-asset")
    publish_asset.add_argument("--asset-id", required=True)
    publish_asset.add_argument("--channel", required=True, choices=["oling", "mapsi_site"])
    publish_asset.add_argument("--dry-run", action="store_true")
    publish_asset.add_argument("--idempotency-key", default="")
    diagnose_asset = subparsers.add_parser("diagnose-asset")
    diagnose_asset.add_argument("--asset-id", required=True)
    diagnose_asset.add_argument("--channel", required=True, choices=["oling", "mapsi_site"])
    mapsi_diagnose = subparsers.add_parser("mapsi-site:diagnose")
    mapsi_diagnose.add_argument("--skip-preview-probe", action="store_true")
    mapsi_recipe = subparsers.add_parser("mapsi-site:recipe")
    mapsi_recipe.add_argument("--asset-id", required=True)
    mapsi_recipe.add_argument("--mode", required=True, choices=["preview", "publish"])
    weekly_pilot_create = subparsers.add_parser("weekly:create-pilot-pack")
    weekly_pilot_create.add_argument("--week-reference")
    weekly_pilot_create.add_argument("--year", type=int)
    weekly_pilot_create.add_argument("--week-number", type=int)
    weekly_generate = subparsers.add_parser("weekly:generate")
    weekly_generate.add_argument("--pack-id", required=True)
    weekly_generate.add_argument("--campaign", choices=["MAPSI_MARKET", "OLING_PRACTICE", "MAPSI_USERS"])
    weekly_status = subparsers.add_parser("weekly:status")
    weekly_status.add_argument("--pack-id", required=True)
    subparsers.add_parser("weekly:return-to-safe-mode")
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


def build_editorial_backend(mode: str | None = None):
    settings = get_settings()
    if mode == "real" or settings.editorial_engine_mode == "real" or settings.editorial_agent_backend == "openai":
        return OpenAIAgentsBackend()
    return SimulatedEditorialBackend()


def _build_mapsi_publisher(session):
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    return MapsiNewsPublisher(
        campaign_repository=repository,
        publication_repository=MapsiNewsPublicationRepository(session),
        connector=MapsiSiteConnector(build_mapsi_site_config()),
        audit_log=audit_log,
        review_portal=review_portal,
    )


def _sanitize_config_report(config: dict) -> dict:
    return {
        key: value
        for key, value in config.items()
        if "token" not in key.lower() and "secret" not in key.lower()
    }


def _mapsi_site_diagnose(*, skip_preview_probe: bool = False) -> dict:
    connector = MapsiSiteConnector(build_mapsi_site_config())
    config = _sanitize_config_report(connector.validate_configuration())
    contract = get_openapi_info()
    auth = {"ok": False, "http_status": None, "result": "unknown"}
    try:
        connector.get_status("__mapsi_site_diagnose__", correlation_id="mapsi-site-diagnose-auth")
    except Exception as exc:
        message = str(exc)
        if "Article not found" in message:
            auth = {"ok": True, "http_status": 404, "result": "authenticated"}
        elif "Missing bearer token" in message:
            auth = {"ok": False, "http_status": 401, "result": "missing_token"}
        elif "Invalid bearer token" in message:
            auth = {"ok": False, "http_status": 403, "result": "invalid_token"}
        else:
            auth = {"ok": False, "http_status": None, "result": message}
    else:
        auth = {"ok": True, "http_status": 200, "result": "unexpected_existing_probe"}

    probe = {"executed": False, "supported": True}
    if not skip_preview_probe:
        example = get_request_example("/api/growth/news", "post")
        example["external_id"] = "mapsi-site-diagnose-probe"
        try:
            draft = connector.create_draft(example, correlation_id="mapsi-site-diagnose-draft")
            preview = connector.get_preview_url(example["external_id"], correlation_id="mapsi-site-diagnose-preview")
            probe = {
                "executed": True,
                "supported": True,
                "growth_external_id": draft["growth_external_id"],
                "remote_article_id": draft["article_id"],
                "preview_url": preview["preview_url"],
                "status": preview["status"],
            }
        except Exception as exc:
            probe = {"executed": True, "supported": False, "error": str(exc)}

    return {
        "target_url": config.get("base_url", ""),
        "public_base_url": config.get("public_base_url", ""),
        "configuration": config,
        "authentication": auth,
        "health": {"ok": auth["ok"], "probe": "GET /api/growth/news/{externalId} expecting 404 ARTICLE_NOT_FOUND"},
        "contract": {
            "version": contract.get("version", ""),
            "title": contract.get("title", ""),
            "unpublish_supported": supports_unpublish(),
        },
        "preview_probe": probe,
    }


def _build_studio_admin_service(session):
    return get_studio_admin_service(session)


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    return str(value)


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
    if args.command in {"generate-weekly-campaign", "generate-campaign"}:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            backend = build_editorial_backend(getattr(args, "mode", None))
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
            backend = build_editorial_backend(getattr(args, "mode", None))
            repository = SqlAlchemyCampaignRepository(session)
            audit_log = SqlAlchemyAuditLogRepository(session)
            service = MultichannelContentService(
                repository=repository,
                review_portal=ReviewPortalService(repository, ReviewPortalRepository(session), audit_log),
                market_strategy_agent=MarketEditorialStrategyAgent(backend),
                newsletter_writer=NewsletterWriterAgent(backend),
                linkedin_writer=LinkedInWriterAgent(backend),
                website_writer=WebsiteArticleWriterAgent(backend),
                mapsi_user_email_writer=MapsiUserEmailWriter(backend),
                oling_writer=OlingArticleWriter(backend),
                mapsi_writer=MapsiArticleWriter(backend),
                mapsi_studio_writer=MapsiStudioContentWriter(backend),
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
            if args.channel == "oling":
                repository = SqlAlchemyCampaignRepository(session)
                audit_log = SqlAlchemyAuditLogRepository(session)
                review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
                service = OlingNewsPublisher(
                    campaign_repository=repository,
                    publication_repository=OlingNewsPublicationRepository(session),
                    connector=OlingConnector(build_oling_config()),
                    audit_log=audit_log,
                    review_portal=review_portal,
                )
            elif args.channel == "mapsi_site":
                service = _build_mapsi_publisher(session)
            else:
                raise SystemExit(f"Unsupported channel: {args.channel}")
            print(
                json.dumps(
                    service.publish_asset(row[0], args.asset_id, dry_run=args.dry_run, idempotency_key=args.idempotency_key),
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
        return 0
    if args.command == "diagnose-asset":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            row = (
                session.query(ContentAssetModel)
                .filter(ContentAssetModel.id == args.asset_id, ContentAssetModel.channel == args.channel)
                .one_or_none()
            )
            if row is None:
                raise SystemExit(f"Unknown asset: {args.asset_id}")
            last_audit = (
                session.query(AuditLogModel)
                .filter(AuditLogModel.campaign_run_id == row.campaign_run_id)
                .order_by(AuditLogModel.created_at.desc())
                .first()
            )
            publication_repository = OlingNewsPublicationRepository(session) if args.channel == "oling" else MapsiNewsPublicationRepository(session)
            publication = publication_repository.get_latest_for_asset(args.asset_id)
            print(
                json.dumps(
                    {
                        "asset_id": row.id,
                        "campaign_id": row.campaign_run_id,
                        "channel": row.channel,
                        "status": row.status,
                        "mode_requested": (publication.publication_mode_requested if publication else row.results.get("publication_mode_requested", "")),
                        "mode_executed": (publication.publication_mode_executed if publication else row.results.get("publication_mode_executed", "")),
                        "publisher": (publication.publisher_type if publication else row.results.get("publisher_type", "")),
                        "approval": {
                            "approved_by": row.approved_by,
                            "approved_at": row.approved_at,
                        },
                        "asset_type": row.asset_type,
                        "fingerprints": {
                            "content_hash": row.content_hash,
                            "approved_content_hash": row.approved_content_hash,
                        },
                        "external_publication_id": row.external_publication_id,
                        "external_publication_url": row.external_publication_url,
                        "published_at": row.published_at,
                        "idempotency_key": publication.idempotency_key if publication else row.results.get("idempotency_key", ""),
                        "idempotent_replay": (publication.metrics.get("idempotent_replay", False) if publication else row.results.get("idempotent_replay", False)),
                        "correlation_id": (publication.metrics.get("correlation_id", "") if publication else row.results.get("correlation_id", "")),
                        "last_audit_event": (
                            {
                                "event_type": last_audit.event_type,
                                "created_at": last_audit.created_at,
                                "payload": last_audit.payload,
                            }
                            if last_audit
                            else None
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
        return 0
    if args.command == "mapsi-site:diagnose":
        print(json.dumps(_mapsi_site_diagnose(skip_preview_probe=args.skip_preview_probe), indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "mapsi-site:recipe":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            row = session.query(ContentAssetModel.campaign_run_id).filter(ContentAssetModel.id == args.asset_id).one_or_none()
            if row is None:
                raise SystemExit(f"Unknown asset: {args.asset_id}")
            publisher = _build_mapsi_publisher(session)
            campaign = publisher.campaign_repository.get(row[0])
            if campaign is None:
                raise SystemExit(f"Unknown campaign for asset: {args.asset_id}")
            asset = next((item for item in campaign.content_assets if item.id == args.asset_id), None)
            if asset is None:
                raise SystemExit(f"Unknown asset: {args.asset_id}")
            if args.mode == "preview":
                result = {
                    "mode": "preview",
                    "asset_id": asset.id,
                    "report": publisher.create_preview(campaign, asset),
                }
            else:
                publication = publisher.publish(campaign, asset)
                status = publisher.get_publication_status(campaign, asset)
                result = {
                    "mode": "publish",
                    "asset_id": asset.id,
                    "publication": {
                        "channel": publication.channel,
                        "external_reference": publication.external_reference,
                        "external_url": publication.external_url,
                    },
                    "report": status,
                }
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    if args.command in {"weekly:create-pilot-pack", "weekly:generate", "weekly:status", "weekly:return-to-safe-mode"}:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            service = _build_studio_admin_service(session)
            actor = "cli"
            correlation_id = f"cli-{uuid4()}"
            if args.command == "weekly:create-pilot-pack":
                if args.week_reference and (args.year is None or args.week_number is None):
                    raise SystemExit("--year and --week-number are required with --week-reference.")
                if args.year is None or args.week_number is None:
                    today = datetime.now(UTC)
                    iso = today.isocalendar()
                    year = iso.year
                    week_number = iso.week
                    week_reference = f"{year}-W{week_number:02d}"
                else:
                    year = args.year
                    week_number = args.week_number
                    week_reference = args.week_reference or f"{year}-W{week_number:02d}"
                print(
                    json.dumps(
                        service.create_weekly_pack(
                            week_reference=week_reference,
                            year=year,
                            week_number=week_number,
                            pilot_mode=True,
                            actor=actor,
                            correlation_id=correlation_id,
                        ),
                        indent=2,
                        sort_keys=True,
                        default=_json_default,
                    )
                )
                return 0
            if args.command == "weekly:generate":
                if args.campaign:
                    payload = service.generate_weekly_pack_campaign(
                        args.pack_id,
                        campaign_type=args.campaign,
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                else:
                    payload = service.generate_weekly_pack(
                        args.pack_id,
                        actor=actor,
                        correlation_id=correlation_id,
                    )
                print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
                return 0
            if args.command == "weekly:status":
                print(json.dumps(service.get_weekly_pack(args.pack_id), indent=2, sort_keys=True, default=_json_default))
                return 0
            print(json.dumps(service.return_to_safe_mode(actor=actor, correlation_id=correlation_id), indent=2, sort_keys=True, default=_json_default))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
