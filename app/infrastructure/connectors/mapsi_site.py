from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import Settings, get_settings
from app.domain.errors import (
    AuthenticationInvalidError,
    AuthenticationRequiredError,
    ExternalConnectorError,
    RateLimitExceededError,
    RemoteConflictError,
    RemoteContractError,
    RemoteNotFoundError,
    RemoteTimeoutError,
    RemoteUnsupportedError,
    RemoteValidationError,
)
from app.infrastructure.observability import incr, structured_log


_CIRCUIT_BREAKERS: dict[str, dict[str, float | int | None]] = {}


class MapsiSiteArticleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    growth_external_id: str
    article_id: int
    version: int
    published_version: int | None = None
    status: str
    slug: str
    preview_url: str | None = None
    public_url: str | None = None
    published_at: str | None = None
    updated_at: str
    idempotent_replay: bool
    correlation_id: str
    has_pending_draft: bool


class MapsiSitePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    growth_external_id: str
    article_id: int
    version: int
    status: str
    slug: str
    preview_url: str
    expires_at: str
    updated_at: str
    idempotent_replay: bool
    correlation_id: str


class MapsiSiteErrorBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] = {}


class MapsiSiteErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: MapsiSiteErrorBody


@dataclass
class MapsiSiteConnectorConfig:
    base_url: str
    public_base_url: str
    api_token: str
    verify_tls: bool
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    circuit_breaker_threshold: int
    circuit_breaker_reset_seconds: int
    mode: str


def build_mapsi_site_config(settings: Settings | None = None) -> MapsiSiteConnectorConfig:
    current = settings or get_settings()
    return MapsiSiteConnectorConfig(
        base_url=current.mapsi_site_base_url.rstrip("/"),
        public_base_url=current.mapsi_site_public_base_url.rstrip("/"),
        api_token=current.mapsi_site_api_token,
        verify_tls=current.mapsi_site_verify_tls,
        timeout_seconds=current.mapsi_site_timeout_seconds,
        max_retries=current.mapsi_site_max_retries,
        retry_backoff_seconds=current.mapsi_site_retry_backoff_seconds,
        circuit_breaker_threshold=current.mapsi_site_circuit_breaker_threshold,
        circuit_breaker_reset_seconds=current.mapsi_site_circuit_breaker_reset_seconds,
        mode=current.mapsi_site_mode,
    )


class MapsiSiteConnector:
    def __init__(self, config: MapsiSiteConnectorConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(base_url=config.base_url, timeout=config.timeout_seconds, verify=config.verify_tls)

    def validate_configuration(self) -> dict[str, Any]:
        missing = []
        if self.config.mode != "mock" and not self.config.base_url:
            missing.append("MAPSI_SITE_BASE_URL")
        if self.config.mode != "mock" and not self.config.public_base_url:
            missing.append("MAPSI_SITE_PUBLIC_BASE_URL")
        if self.config.mode != "mock" and not self.config.api_token:
            missing.append("MAPSI_SITE_API_TOKEN")
        return {
            "mode": self.config.mode,
            "base_url": self.config.base_url,
            "public_base_url": self.config.public_base_url,
            "configured": not missing,
            "missing": missing,
        }

    def create_draft(self, payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
        return self._parse_article(self._request("POST", "/api/growth/news", json=payload, correlation_id=correlation_id))

    def update_draft(self, external_id: str, payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
        return self._parse_article(self._request("PATCH", f"/api/growth/news/{external_id}", json=payload, correlation_id=correlation_id))

    def get_preview_url(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._parse_preview(self._request("POST", f"/api/growth/news/{external_id}/preview-url", correlation_id=correlation_id))

    def publish(self, external_id: str, *, correlation_id: str, idempotency_key: str = "") -> dict[str, Any]:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return self._parse_article(
            self._request(
                "POST",
                f"/api/growth/news/{external_id}/publish",
                correlation_id=correlation_id,
                headers=headers,
                retry_on_transport_errors=False,
            )
        )

    def get_status(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._parse_article(self._request("GET", f"/api/growth/news/{external_id}", correlation_id=correlation_id))

    def unpublish(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._parse_article(self._request("POST", f"/api/growth/news/{external_id}/unpublish", correlation_id=correlation_id))

    def _request(self, method: str, path: str, *, correlation_id: str, retry_on_transport_errors: bool = True, **kwargs) -> httpx.Response:
        self._assert_circuit_closed(correlation_id)
        headers = kwargs.pop("headers", {})
        headers["Accept"] = "application/json"
        headers["X-Correlation-ID"] = correlation_id
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        attempts = max(self.config.max_retries, 0) + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.client.request(method, path, headers=headers, **kwargs)
                if response.status_code == 429:
                    self._record_failure(correlation_id, response.status_code)
                    if attempt < attempts:
                        time.sleep(self.config.retry_backoff_seconds * attempt)
                        continue
                    raise RateLimitExceededError("Mapsi Site API rate limit reached.")
                if 500 <= response.status_code <= 599:
                    self._record_failure(correlation_id, response.status_code)
                    if attempt < attempts:
                        time.sleep(self.config.retry_backoff_seconds * attempt)
                        continue
                response.raise_for_status()
                self._record_success()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                raise self._raise_http_error(exc.response, correlation_id) from exc
            except httpx.TimeoutException as exc:
                last_error = exc
                self._record_failure(correlation_id, None)
                structured_log("mapsi_site.http_timeout", correlation_id=correlation_id, mode=self.config.mode, error_type=exc.__class__.__name__)
                incr("mapsi_site.http_timeout")
                raise RemoteTimeoutError("Mapsi Site API request timed out.") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                self._record_failure(correlation_id, None)
                if retry_on_transport_errors and attempt < attempts:
                    time.sleep(self.config.retry_backoff_seconds * attempt)
                    continue
                structured_log("mapsi_site.http_error", correlation_id=correlation_id, mode=self.config.mode, error_type=exc.__class__.__name__)
                incr("mapsi_site.http_error")
                raise ExternalConnectorError("Mapsi Site API request failed.") from exc
        raise ExternalConnectorError("Mapsi Site API request failed.") from last_error

    def _raise_http_error(self, response: httpx.Response, correlation_id: str) -> ExternalConnectorError:
        payload = self._raw_json(response)
        error = self._extract_error(payload)
        message = error.get("message") or payload.get("message") or payload.get("detail") or response.text[:300]
        structured_log("mapsi_site.api_error", correlation_id=correlation_id, mode=self.config.mode, status_code=response.status_code, message=message)
        incr("mapsi_site.api_error")
        if response.status_code == 429:
            return RateLimitExceededError("Mapsi Site API rate limit reached.")
        if response.status_code == 401:
            return AuthenticationRequiredError(message)
        if response.status_code == 403:
            return AuthenticationInvalidError(message)
        if response.status_code == 404:
            return RemoteNotFoundError(message)
        if response.status_code == 409 and error.get("code") == "UNPUBLISH_NOT_SUPPORTED":
            return RemoteUnsupportedError(message)
        if response.status_code == 409:
            return RemoteConflictError(message)
        if response.status_code == 422:
            return RemoteValidationError(message)
        if 400 <= response.status_code <= 499:
            return ExternalConnectorError(f"Mapsi Site API client error: {response.status_code} {message}".strip())
        return ExternalConnectorError(f"Mapsi Site API server error: {response.status_code} {message}".strip())

    def _parse_article(self, response: httpx.Response) -> dict[str, Any]:
        try:
            return MapsiSiteArticleResponse.model_validate(self._raw_json(response)).model_dump()
        except ValidationError as exc:
            raise RemoteContractError("Mapsi Site API article response does not match the published contract.") from exc

    def _parse_preview(self, response: httpx.Response) -> dict[str, Any]:
        try:
            return MapsiSitePreviewResponse.model_validate(self._raw_json(response)).model_dump()
        except ValidationError as exc:
            raise RemoteContractError("Mapsi Site API preview response does not match the published contract.") from exc

    def _raw_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise RemoteContractError("Mapsi Site API returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise RemoteContractError("Mapsi Site API returned an invalid JSON payload.")
        try:
            return dict(payload)
        except Exception as exc:
            raise RemoteContractError("Mapsi Site API returned an invalid JSON payload.") from exc

    def _extract_error(self, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = payload.get("error")
        if isinstance(envelope, dict):
            return envelope
        detail = payload.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
            return detail["error"]
        return {}

    def _breaker_state(self) -> dict[str, float | int | None]:
        key = self.config.base_url or "mapsi_site"
        state = _CIRCUIT_BREAKERS.get(key)
        if state is None:
            state = {"failures": 0, "opened_at": None}
            _CIRCUIT_BREAKERS[key] = state
        return state

    def _assert_circuit_closed(self, correlation_id: str) -> None:
        state = self._breaker_state()
        opened_at = state["opened_at"]
        if opened_at is None:
            return
        if (time.time() - float(opened_at)) >= self.config.circuit_breaker_reset_seconds:
            state["failures"] = 0
            state["opened_at"] = None
            return
        structured_log("mapsi_site.circuit_open", correlation_id=correlation_id, mode=self.config.mode)
        incr("mapsi_site.circuit_open")
        raise ExternalConnectorError("Mapsi Site circuit breaker is open.")

    def _record_success(self) -> None:
        state = self._breaker_state()
        state["failures"] = 0
        state["opened_at"] = None

    def _record_failure(self, correlation_id: str, status_code: int | None) -> None:
        state = self._breaker_state()
        failures = int(state["failures"]) + 1
        state["failures"] = failures
        if failures >= self.config.circuit_breaker_threshold:
            state["opened_at"] = time.time()
            structured_log("mapsi_site.circuit_opened", correlation_id=correlation_id, mode=self.config.mode, failures=failures, status_code=status_code)
            incr("mapsi_site.circuit_opened")
