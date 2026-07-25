from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass

from app.core.db import Base, SessionLocal, engine
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors.mapsi_site_contract import get_openapi_info, get_request_example, supports_unpublish
from app.knowledge import KnowledgeRepository, validate_knowledge_base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mapsi-growth")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mapsi_diagnose = subparsers.add_parser("mapsi-site:diagnose")
    mapsi_diagnose.add_argument("--skip-preview-probe", action="store_true")

    subparsers.add_parser("knowledge:validate")
    return parser


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    return str(value)


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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "mapsi-site:diagnose":
        print(json.dumps(_mapsi_site_diagnose(skip_preview_probe=args.skip_preview_probe), indent=2, sort_keys=True, default=str))
        return 0

    if args.command == "knowledge:validate":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            report = validate_knowledge_base()
            repository = KnowledgeRepository(session)
            payload = {
                "ok": report.ok,
                "version_hash": report.version_hash,
                "mapsi_feature_ids": report.mapsi_feature_ids,
                "oling_practice_ids": report.oling_practice_ids,
                "published_topic_history_count": len(repository.getPublishedTopicHistory()),
                "errors": report.errors,
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
        return 0 if report.ok else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
