from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Query

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


def _locale_state(article: dict, locale: str | None = None) -> dict:
    requested = locale or article.get("locale", "fr")
    for item in article.get("locales", []):
        if item.get("locale") == requested:
            return item
    return {"locale": requested, "slug": article["slug"], "status": "draft", "published_at": None, "unpublished_at": None}


def _status_payload(article: dict, http_code: int = 200, locale: str | None = None) -> dict:
    current = _locale_state(article, locale)
    published = current.get("published_revision_number")
    draft = current.get("draft_revision_number")
    if published is None and current.get("status") == "published":
        published = article.get("published_revision_number")
    if draft is None:
        draft = article.get("draft_revision_number")
    return {
        "http_code": http_code,
        "external_id": article["external_id"],
        "locale": current.get("locale", article.get("locale", "fr")),
        "content_group_id": article.get("content_group_id", ""),
        "locales": article.get("locales", []),
        "public_slug": current.get("slug", article["slug"]),
        "publication_status": current.get("status", article["publication_status"]),
        "has_pending_draft": draft is not None and (published is None or draft > published),
        "draft_revision_number": draft,
        "published_revision_number": published,
        "published_at": current.get("published_at"),
        "unpublished_at": current.get("unpublished_at"),
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
        locale = payload.get("locale", "fr")
        article = {
            "external_id": external_id,
            "locale": locale,
            "content_group_id": payload.get("content_group_id", ""),
            "slug": payload["slug"],
            "locales": [{"locale": locale, "slug": payload["slug"], "status": "draft", "published_at": None, "unpublished_at": None, "draft_revision_number": 1, "published_revision_number": None}],
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
    locale = payload.get("locale", article.get("locale", "fr"))
    article["slug"] = payload["slug"]
    article["locale"] = locale
    article["content_group_id"] = payload.get("content_group_id", article.get("content_group_id", ""))
    article["draft_revision_number"] = (article.get("draft_revision_number") or 0) + 1
    article["locales"] = _upsert_locale(article.get("locales", []), locale, payload["slug"], "draft", draft_revision_number=article["draft_revision_number"])
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
    locale = payload.get("locale", article.get("locale", "fr"))
    article["slug"] = payload["slug"]
    article["locale"] = locale
    article["content_group_id"] = payload.get("content_group_id", article.get("content_group_id", ""))
    article["draft_revision_number"] = (article.get("draft_revision_number") or 0) + 1
    article["locales"] = _upsert_locale(article.get("locales", []), locale, payload["slug"], "draft", draft_revision_number=article["draft_revision_number"])
    article["payload"] = payload
    article["publication_status"] = "draft"
    article["last_correlation_id"] = x_correlation_id
    return _status_payload(article, 200)


@app.post("/api/growth/news/{external_id}/preview-url")
def preview_url(external_id: str, locale: str | None = Query(default=None), authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    current = _locale_state(article, locale)
    if current.get("draft_revision_number") is None:
        raise HTTPException(status_code=409, detail="No draft available for preview.")
    expires_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "external_id": external_id,
        "preview_url": f"http://testserver/preview/ressources/{current['slug']}?token=preview-{external_id}",
        "expires_at": expires_at,
    }


@app.post("/api/growth/news/{external_id}/publish")
def publish(external_id: str, locale: str | None = Query(default=None), authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    current = _locale_state(article, locale)
    if current.get("draft_revision_number") is None:
        raise HTTPException(status_code=409, detail="No draft available for publication.")
    published_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    article["published_revision_number"] = current["draft_revision_number"]
    article["publication_status"] = "published"
    article["published_at"] = published_at
    article["locales"] = _upsert_locale(
        article.get("locales", []),
        current["locale"],
        current["slug"],
        "published",
        published_at,
        current.get("draft_revision_number"),
        current.get("draft_revision_number"),
    )
    return _status_payload(article, 200, current["locale"])


@app.get("/api/growth/news/{external_id}")
def status(external_id: str, locale: str | None = Query(default=None), authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    return _status_payload(article, 200, locale)


@app.post("/api/growth/news/{external_id}/unpublish")
def unpublish(external_id: str, locale: str | None = Query(default=None), authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    current = _locale_state(article, locale)
    if current.get("status") != "published":
        raise HTTPException(status_code=409, detail="Only a published article can be unpublished.")
    unpublished_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    article["publication_status"] = "unpublished"
    article["unpublished_at"] = unpublished_at
    article["locales"] = _upsert_locale(
        article.get("locales", []),
        current["locale"],
        current["slug"],
        "unpublished",
        current.get("published_at"),
        current.get("draft_revision_number"),
        current.get("published_revision_number"),
        unpublished_at,
    )
    return _status_payload(article, 200, current["locale"])


def _upsert_locale(
    locales: list[dict],
    locale: str,
    slug: str,
    status: str,
    published_at: str | None = None,
    draft_revision_number: int | None = None,
    published_revision_number: int | None = None,
    unpublished_at: str | None = None,
) -> list[dict]:
    existing = next((item for item in locales if item.get("locale") == locale), {})
    next_locales = [item for item in locales if item.get("locale") != locale]
    next_locales.append({
        "locale": locale,
        "slug": slug,
        "status": status,
        "published_at": published_at,
        "unpublished_at": unpublished_at,
        "draft_revision_number": draft_revision_number if draft_revision_number is not None else existing.get("draft_revision_number"),
        "published_revision_number": published_revision_number if published_revision_number is not None else existing.get("published_revision_number"),
    })
    return sorted(next_locales, key=lambda item: str(item.get("locale", "")))


@app.post("/api/growth/news/{external_id}/restore-previous")
def restore_previous(external_id: str, locale: str | None = Query(default=None), authorization: str | None = Header(default=None)) -> dict:
    _assert_auth(authorization)
    article = STATE["articles"].get(external_id)
    if article is None:
        raise HTTPException(status_code=404, detail="unknown external_id")
    current = _locale_state(article, locale)
    if current.get("published_revision_number") is None or current["published_revision_number"] < 2:
        raise HTTPException(status_code=409, detail="No previous published version is available.")
    article["publication_status"] = "published"
    article["published_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    article["unpublished_at"] = None
    return _status_payload(article, 200, current["locale"])
