from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="Mock Oling")

STATE: dict[str, dict] = {
    "articles": {},
    "preview_tokens": {},
}

VALID_TOKEN = "oling-test-token"


def _assert_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    if authorization.removeprefix("Bearer ").strip() != VALID_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid bearer token.")


def _status_payload(article: dict, http_code: int = 200) -> dict:
    published = article.get("published_revision_number")
    draft = article.get("draft_revision_number")
    return {
        "http_code": http_code,
        "external_id": article["external_id"],
        "public_slug": article["slug"],
        "publication_status": article["publication_status"],
        "has_pending_draft": draft is not None and (published is None or draft > published),
        "draft_revision_number": draft,
        "published_revision_number": published,
        "published_at": article.get("published_at"),
        "unpublished_at": article.get("unpublished_at"),
    }


@app.post("/api/growth/news")
def create_or_update_draft(payload: dict, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    if payload.get("title") == "RATE_LIMIT":
        raise HTTPException(status_code=429, detail="rate limited")
    if payload.get("title") == "SERVER_ERROR":
        raise HTTPException(status_code=500, detail="server error")
    if payload.get("title") == "CLIENT_ERROR":
        raise HTTPException(status_code=422, detail="invalid payload")
    external_id = payload["external_id"]
    article = STATE["articles"].get(external_id)
    if article is None:
        article = {
            "external_id": external_id,
            "slug": payload["slug"],
            "draft_revision_number": 1,
            "published_revision_number": None,
            "publication_status": "draft",
            "published_at": None,
            "unpublished_at": None,
            "payload": payload,
            "last_correlation_id": x_correlation_id,
        }
        STATE["articles"][external_id] = article
        return _status_payload(article, 201)
    article["slug"] = payload["slug"]
    article["draft_revision_number"] = (article.get("draft_revision_number") or 0) + 1
    article["payload"] = payload
    article["publication_status"] = "draft"
    article["last_correlation_id"] = x_correlation_id
    return _status_payload(article, 200)


@app.patch("/api/growth/news/{external_id}")
def update_draft(external_id: str, payload: dict, authorization: str | None = Header(default=None), x_correlation_id: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    if payload.get("external_id") != external_id:
        raise HTTPException(status_code=400, detail="external_id mismatch")
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    article["slug"] = payload["slug"]
    article["draft_revision_number"] = (article.get("draft_revision_number") or 0) + 1
    article["payload"] = payload
    article["publication_status"] = "draft"
    article["last_correlation_id"] = x_correlation_id
    return _status_payload(article, 200)


@app.post("/api/growth/news/{external_id}/preview-url")
def preview_url(external_id: str, authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    if article.get("draft_revision_number") is None:
        raise HTTPException(status_code=409, detail="No draft available for preview.")
    expires_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "external_id": external_id,
        "preview_url": f"http://testserver/preview/ressources/{article['slug']}?token=preview-{external_id}",
        "expires_at": expires_at,
    }


@app.post("/api/growth/news/{external_id}/publish")
def publish(external_id: str, authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    if article.get("draft_revision_number") is None:
        raise HTTPException(status_code=409, detail="No draft available for publication.")
    article["published_revision_number"] = article["draft_revision_number"]
    article["publication_status"] = "published"
    article["published_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    return _status_payload(article, 200)


@app.get("/api/growth/news/{external_id}")
def status(external_id: str, authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    return _status_payload(article, 200)


@app.post("/api/growth/news/{external_id}/unpublish")
def unpublish(external_id: str, authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    if article.get("publication_status") != "published":
        raise HTTPException(status_code=409, detail="Only a published article can be unpublished.")
    article["publication_status"] = "unpublished"
    article["unpublished_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    return _status_payload(article, 200)


@app.post("/api/growth/news/{external_id}/restore-previous")
def restore_previous(external_id: str, authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    if article.get("published_revision_number") is None or article["published_revision_number"] < 2:
        raise HTTPException(status_code=409, detail="No previous published version is available.")
    article["publication_status"] = "published"
    article["published_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    article["unpublished_at"] = None
    return _status_payload(article, 200)
