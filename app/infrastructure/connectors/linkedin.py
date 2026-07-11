from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

from httpx import Client, HTTPStatusError

from app.core.config import Settings, get_settings
from app.domain.errors import ExternalConnectorError, RateLimitExceededError
from app.infrastructure.observability import incr, structured_log


@dataclass
class LinkedInConnectorConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    company_id: str
    organization_urn: str
    access_token: str
    refresh_token: str
    scope: str
    api_version: str
    verify_tls: bool
    mode: str
    base_url: str = "https://api.linkedin.com"


def build_linkedin_config(settings: Settings | None = None) -> LinkedInConnectorConfig:
    current = settings or get_settings()
    organization_urn = current.linkedin_organization_urn or f"urn:li:organization:{current.linkedin_company_id}"
    return LinkedInConnectorConfig(
        client_id=current.linkedin_client_id,
        client_secret=current.linkedin_client_secret,
        redirect_uri=current.linkedin_redirect_uri,
        company_id=current.linkedin_company_id,
        organization_urn=organization_urn,
        access_token=current.linkedin_access_token,
        refresh_token=current.linkedin_refresh_token,
        scope=current.linkedin_scope,
        api_version=current.linkedin_api_version,
        verify_tls=current.linkedin_verify_tls,
        mode=current.linkedin_mode,
    )


class LinkedInConnector:
    def __init__(self, config: LinkedInConnectorConfig, client: Client | None = None) -> None:
        self.config = config
        self.client = client or Client(base_url=config.base_url.rstrip("/"), timeout=20.0, verify=config.verify_tls)

    def build_authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "scope": self.config.scope,
                "state": state,
            }
        )
        return f"https://www.linkedin.com/oauth/v2/authorization?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        response = self._request("POST", "/oauth/v2/accessToken", data=payload, auth_required=False)
        return self._token_payload(response)

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        response = self._request("POST", "/oauth/v2/accessToken", data=payload, auth_required=False)
        return self._token_payload(response)

    def get_organization(self, organization_urn: str | None = None) -> dict[str, Any]:
        target_urn = organization_urn or self.config.organization_urn
        organization_id = target_urn.rsplit(":", 1)[-1]
        response = self._request("GET", f"/rest/organizations/{organization_id}")
        payload = response.json()
        return {
            "id": str(payload.get("id", organization_id)),
            "urn": payload.get("urn", target_urn),
            "name": payload.get("localizedName", payload.get("name", "")),
            "vanity_name": payload.get("vanityName", ""),
        }

    def initialize_image_upload(self, owner_urn: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/rest/images?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": owner_urn}},
        )
        payload = response.json().get("value", response.json())
        return {
            "image_urn": payload.get("image"),
            "upload_url": payload.get("uploadUrl"),
        }

    def upload_media(self, upload_url: str, content: bytes, content_type: str) -> None:
        if not upload_url:
            raise ExternalConnectorError("LinkedIn upload URL is missing.")
        response = self.client.put(upload_url, content=content, headers={"Content-Type": content_type})
        if response.status_code >= 400:
            self._raise_http_error(response)

    def create_post(self, *, author_urn: str, commentary: str, media_urns: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if media_urns:
            payload["content"] = {
                "media": [{"id": media_urn} for media_urn in media_urns],
            }
        response = self._request("POST", "/rest/posts", json=payload)
        header_urn = response.headers.get("x-linkedin-id", "")
        payload = response.json() if response.content else {}
        post_urn = payload.get("id") or header_urn
        return {"post_urn": post_urn, "status": payload.get("lifecycleState", "PUBLISHED")}

    def get_post_metrics(self, post_urn: str) -> dict[str, Any]:
        encoded = quote(post_urn, safe="")
        response = self._request("GET", f"/rest/posts/{encoded}/metrics")
        payload = response.json()
        return {
            "impressions": int(payload.get("impressions", 0)),
            "unique_impressions": int(payload.get("uniqueImpressions", 0)),
            "clicks": int(payload.get("clicks", 0)),
            "reactions": int(payload.get("reactions", 0)),
            "comments": int(payload.get("comments", 0)),
            "shares": int(payload.get("shares", 0)),
            "engagement_rate": float(payload.get("engagementRate", 0.0)),
        }

    def _token_payload(self, response) -> dict[str, Any]:
        payload = response.json()
        now = datetime.now(UTC)
        return {
            "access_token": payload.get("access_token", ""),
            "refresh_token": payload.get("refresh_token", ""),
            "scope": payload.get("scope", self.config.scope),
            "expires_at": now + timedelta(seconds=int(payload.get("expires_in", 0) or 0)) if payload.get("expires_in") else None,
            "refresh_expires_at": now + timedelta(seconds=int(payload.get("refresh_token_expires_in", 0) or 0))
            if payload.get("refresh_token_expires_in")
            else None,
        }

    def _request(self, method: str, path: str, *, auth_required: bool = True, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.setdefault("Accept", "application/json")
        if path.startswith("/rest/"):
            headers.setdefault("LinkedIn-Version", self.config.api_version)
            headers.setdefault("X-Restli-Protocol-Version", "2.0.0")
        if auth_required:
            token = self.config.access_token
            if not token:
                raise ExternalConnectorError("LinkedIn access token is not configured.")
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except HTTPStatusError as exc:
            self._raise_http_error(exc.response)

    def _raise_http_error(self, response) -> None:
        payload = {}
        try:
            payload = response.json()
        except Exception:
            payload = {"message": response.text[:300]}
        structured_log(
            "linkedin.api_error",
            status_code=response.status_code,
            mode=self.config.mode,
            message=payload.get("message", ""),
        )
        incr("linkedin.api_error")
        if response.status_code == 429:
            raise RateLimitExceededError("LinkedIn API rate limit reached.")
        raise ExternalConnectorError(f"LinkedIn API error: {response.status_code}")
