from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response

app = FastAPI(title="Mock Mapsi Site News")

STATE: dict[str, Any] = {
    "articles": {},
    "preview_tokens": {},
    "next_article_id": 1,
    "supports_unpublish": True,
}

VALID_TOKEN = "mapsi-site-test-token"


def _correlation_id(value: str | None) -> str:
    return (value or "mock-correlation")[:100]


def _error(status_code: int, code: str, message: str, correlation_id: str, details: dict[str, Any] | None = None) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": correlation_id,
                "details": details or {},
            }
        },
    )


def _assert_auth(authorization: str | None, correlation_id: str) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        _error(401, "AUTHENTICATION_REQUIRED", "Missing bearer token.", correlation_id)
    if authorization.removeprefix("Bearer ").strip() != VALID_TOKEN:
        _error(403, "AUTHENTICATION_INVALID", "Invalid bearer token.", correlation_id)


def _updated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _article_response(article: dict[str, Any], correlation_id: str, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "growth_external_id": article["growth_external_id"],
        "article_id": article["article_id"],
        "version": article["published_version"] if article["status"] == "published" else article["draft_version"],
        "published_version": article["published_version"],
        "status": article["status"],
        "slug": article["published_slug"] if article["status"] == "published" else article["draft_slug"],
        "preview_url": None,
        "public_url": article["public_url"],
        "published_at": article["published_at"],
        "updated_at": article["updated_at"],
        "idempotent_replay": idempotent_replay,
        "correlation_id": correlation_id,
        "has_pending_draft": article["has_pending_draft"],
    }


def _preview_response(article: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    token = STATE["preview_tokens"][article["growth_external_id"]]
    return {
        "growth_external_id": article["growth_external_id"],
        "article_id": article["article_id"],
        "version": article["draft_version"],
        "status": article["status"],
        "slug": article["draft_slug"],
        "preview_url": f"http://testserver/preview/actualites/{article['draft_slug']}?token={token['token']}",
        "expires_at": token["expires_at"],
        "updated_at": article["updated_at"],
        "idempotent_replay": False,
        "correlation_id": correlation_id,
    }


def _validate_payload(payload: dict[str, Any], correlation_id: str, external_id: str | None = None) -> None:
    if external_id is not None and payload.get("external_id") != external_id:
        _error(422, "INVALID_CONTENT", "external_id mismatch.", correlation_id)
    if not str(payload.get("external_id", "")).strip():
        _error(422, "INVALID_CONTENT", "external_id is required.", correlation_id, {"fields": {"external_id": "external_id is required."}})
    if not str(payload.get("title", "")).strip():
        _error(422, "INVALID_CONTENT", "title is required.", correlation_id, {"fields": {"title": "title is required."}})
    if not str(payload.get("content_html", "")).strip():
        _error(422, "INVALID_CONTENT", "content_html is invalid.", correlation_id, {"fields": {"content_html": "content_html is invalid."}})


def _article_or_404(external_id: str, correlation_id: str) -> dict[str, Any]:
    article = STATE["articles"].get(external_id)
    if article is None:
        _error(404, "ARTICLE_NOT_FOUND", "Article not found.", correlation_id)
    return article


def _content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()


@app.post("/api/growth/news")
def create_draft(payload: dict[str, Any], authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    if payload.get("title") == "RATE_LIMIT":
        _error(429, "INTERNAL_ERROR", "Rate limit exceeded.", correlation_id)
    if payload.get("title") == "SERVER_ERROR":
        _error(500, "INTERNAL_ERROR", "Internal error.", correlation_id)
    if payload.get("title") == "CONTRACT_ERROR":
        return {"broken": True}
    _validate_payload(payload, correlation_id)

    external_id = payload["external_id"]
    article = STATE["articles"].get(external_id)
    content_hash = _content_hash(payload)
    created = article is None
    if article is None:
        article = {
            "growth_external_id": external_id,
            "article_id": STATE["next_article_id"],
            "draft_slug": payload.get("slug") or "actualite-mapsi",
            "published_slug": None,
            "draft_version": 0,
            "published_version": None,
            "status": "draft",
            "published_at": None,
            "updated_at": _updated_at(),
            "public_url": None,
            "has_pending_draft": False,
            "content_hash": "",
            "last_publication_idempotency_key": "",
        }
        STATE["next_article_id"] += 1
        STATE["articles"][external_id] = article

    if article["content_hash"] != content_hash:
        article["draft_version"] += 1
    article["draft_slug"] = payload.get("slug") or article["draft_slug"]
    article["status"] = "draft"
    article["updated_at"] = _updated_at()
    article["has_pending_draft"] = article["published_version"] is not None and article["draft_version"] != article["published_version"]
    article["content_hash"] = content_hash
    return Response(
        content=__import__("json").dumps(_article_response(article, correlation_id, idempotent_replay=False)),
        status_code=201 if created else 200,
        media_type="application/json",
    )


@app.patch("/api/growth/news/{external_id}")
def update_draft(external_id: str, payload: dict[str, Any], authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    _validate_payload(payload, correlation_id, external_id)
    article = _article_or_404(external_id, correlation_id)
    content_hash = _content_hash(payload)
    if article["content_hash"] != content_hash:
        article["draft_version"] += 1
    article["draft_slug"] = payload.get("slug") or article["draft_slug"]
    article["status"] = "draft"
    article["updated_at"] = _updated_at()
    article["has_pending_draft"] = article["published_version"] is not None and article["draft_version"] != article["published_version"]
    article["content_hash"] = content_hash
    return _article_response(article, correlation_id, idempotent_replay=False)


@app.post("/api/growth/news/{external_id}/preview-url")
def preview_url(external_id: str, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    article = _article_or_404(external_id, correlation_id)
    if article["draft_version"] == 0:
        _error(409, "VERSION_CONFLICT", "No draft available for preview.", correlation_id)
    expires_at = (datetime.now(UTC) + timedelta(hours=2)).replace(microsecond=0).isoformat()
    STATE["preview_tokens"][external_id] = {"token": f"preview-{external_id}", "expires_at": expires_at}
    return _preview_response(article, correlation_id)


@app.post("/api/growth/news/{external_id}/publish")
def publish(external_id: str, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    article = _article_or_404(external_id, correlation_id)
    if article["draft_version"] == 0:
        _error(409, "PUBLICATION_NOT_ALLOWED", "No draft available for publication.", correlation_id)
    if article["status"] == "published" and not article["has_pending_draft"]:
        return _article_response(article, correlation_id, idempotent_replay=True)
    article["published_version"] = article["draft_version"]
    article["published_slug"] = article["draft_slug"]
    article["status"] = "published"
    article["published_at"] = _updated_at()
    article["updated_at"] = article["published_at"]
    article["public_url"] = f"https://www.mapsi.fr/actualites/{article['published_slug']}"
    article["has_pending_draft"] = False
    article["last_publication_idempotency_key"] = idempotency_key or ""
    return _article_response(article, correlation_id, idempotent_replay=False)


@app.get("/api/growth/news/{external_id}")
def status(external_id: str, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    return _article_response(_article_or_404(external_id, correlation_id), correlation_id, idempotent_replay=False)


@app.post("/api/growth/news/{external_id}/unpublish")
def unpublish(external_id: str, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict[str, Any]:
    correlation_id = _correlation_id(x_correlation_id)
    _assert_auth(authorization, correlation_id)
    if not STATE["supports_unpublish"]:
        _error(409, "UNPUBLISH_NOT_SUPPORTED", "Unpublish is not supported.", correlation_id)
    article = _article_or_404(external_id, correlation_id)
    if article["status"] != "published":
        _error(409, "VERSION_CONFLICT", "Only a published article can be unpublished.", correlation_id)
    article["status"] = "unpublished"
    article["updated_at"] = _updated_at()
    article["public_url"] = None
    return _article_response(article, correlation_id, idempotent_replay=False)
