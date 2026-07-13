import logging

from fastapi import FastAPI

from app.contracts import read_contract_metadata
from app.entrypoints.api.routes.campaigns import router as campaigns_router
from app.entrypoints.api.routes.github_webhooks import router as github_webhooks_router
from app.entrypoints.api.routes.operations import router as operations_router
from app.entrypoints.api.routes.review_portal import router as review_portal_router
from app.entrypoints.api.routes.studio_admin import router as studio_admin_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="MAPSI Growth Factory", version="0.1.0")

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(campaigns_router)
    app.include_router(operations_router)
    app.include_router(github_webhooks_router)
    app.include_router(review_portal_router)
    app.include_router(studio_admin_router)

    @app.on_event("startup")
    def log_contract_sha() -> None:
        metadata = read_contract_metadata()
        logger.info(
            "MAPSI contract loaded: version=%s ref=%s sha=%s",
            metadata.get("contract_version", "missing"),
            metadata.get("source_ref", "missing"),
            metadata.get("source_sha", "missing"),
        )

    return app


app = create_app()
