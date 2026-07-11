from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Response

app = FastAPI(title="Mock LinkedIn")

STATE = {
    "tokens": {},
    "organizations": {
        "3347696": {
            "id": "3347696",
            "urn": "urn:li:organization:3347696",
            "localizedName": "OLING",
            "vanityName": "oling",
        }
    },
    "posts": {},
    "metrics": {},
    "uploads": {},
}


@app.post("/oauth/v2/accessToken")
def issue_token(grant_type: str = "", code: str = "", refresh_token: str = "") -> dict:
    token = f"mock-token-{len(STATE['tokens']) + 1}"
    refreshed = refresh_token or "mock-refresh-token"
    if grant_type == "refresh_token" and refresh_token == "expired":
        raise HTTPException(status_code=401, detail="refresh token expired")
    STATE["tokens"][token] = {"code": code, "refresh_token": refreshed}
    return {
        "access_token": token,
        "expires_in": 3600,
        "refresh_token": refreshed,
        "refresh_token_expires_in": 86400,
        "scope": "w_organization_social r_organization_social",
    }


@app.get("/rest/organizations/{organization_id}")
def get_organization(organization_id: str, authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing auth")
    organization = STATE["organizations"].get(organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="unknown organization")
    return organization


@app.post("/rest/images")
def initialize_upload(action: str, payload: dict, authorization: str | None = Header(default=None)) -> dict:
    if action != "initializeUpload":
        raise HTTPException(status_code=400, detail="unsupported action")
    if not authorization:
        raise HTTPException(status_code=401, detail="missing auth")
    image_urn = f"urn:li:image:{len(STATE['uploads']) + 1}"
    upload_url = f"http://testserver/upload/{len(STATE['uploads']) + 1}"
    STATE["uploads"][upload_url] = {"image_urn": image_urn, "owner": payload["initializeUploadRequest"]["owner"]}
    return {"value": {"image": image_urn, "uploadUrl": upload_url}}


@app.put("/upload/{upload_id}")
def upload_media(upload_id: str, response: Response) -> dict:
    upload_url = f"http://testserver/upload/{upload_id}"
    if upload_url not in STATE["uploads"]:
        raise HTTPException(status_code=404, detail="upload not found")
    response.status_code = 201
    return {}


@app.post("/rest/posts")
def create_post(payload: dict, response: Response, authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing auth")
    if payload["commentary"] == "RATE_LIMIT":
        raise HTTPException(status_code=429, detail="too many requests")
    post_urn = f"urn:li:share:{len(STATE['posts']) + 1}"
    STATE["posts"][post_urn] = payload
    STATE["metrics"].setdefault(
        post_urn,
        {
            "impressions": 120,
            "uniqueImpressions": 100,
            "clicks": 12,
            "reactions": 8,
            "comments": 2,
            "shares": 1,
            "engagementRate": 0.19,
        },
    )
    response.headers["x-linkedin-id"] = post_urn
    return {"id": post_urn, "lifecycleState": "PUBLISHED"}


@app.get("/rest/posts/{post_urn:path}/metrics")
def get_metrics(post_urn: str, authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing auth")
    normalized = post_urn.replace("%3A", ":")
    metrics = STATE["metrics"].get(normalized)
    if metrics is None:
        raise HTTPException(status_code=404, detail="post not found")
    return metrics
