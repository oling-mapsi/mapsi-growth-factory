from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.domain.errors import ExternalConnectorError, RateLimitExceededError
from app.infrastructure.observability import incr, structured_log


_CIRCUIT_BREAKERS: dict[str, dict[str, float | int | None]] = {}


@dataclass
class OlingConnectorConfig:
    base_url: str
    site_base_url: str
    api_token: str
    verify_tls: bool
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    circuit_breaker_threshold: int
    circuit_breaker_reset_seconds: int
    mode: str


def build_oling_config(settings: Settings | None = None) -> OlingConnectorConfig:
    current = settings or get_settings()
    return OlingConnectorConfig(
        base_url=current.oling_base_url.rstrip("/"),
        site_base_url=current.oling_site_base_url.rstrip("/"),
        api_token=current.oling_api_token,
        verify_tls=current.oling_verify_tls,
        timeout_seconds=current.oling_timeout_seconds,
        max_retries=current.oling_max_retries,
        retry_backoff_seconds=current.oling_retry_backoff_seconds,
        circuit_breaker_threshold=current.oling_circuit_breaker_threshold,
        circuit_breaker_reset_seconds=current.oling_circuit_breaker_reset_seconds,
        mode=current.oling_mode,
    )


class OlingConnector:
    def __init__(self, config: OlingConnectorConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            verify=config.verify_tls,
        )

    def validate_configuration(self) -> dict[str, Any]:
        missing = []
        if self.config.mode != "mock" and not self.config.base_url:
            missing.append("OLING_BASE_URL")
        if self.config.mode != "mock" and not self.config.site_base_url:
            missing.append("OLING_SITE_BASE_URL")
        if self.config.mode != "mock" and not self.config.api_token:
            missing.append("OLING_API_TOKEN")
        return {
            "mode": self.config.mode,
            "base_url": self.config.base_url,
            "site_base_url": self.config.site_base_url,
            "configured": not missing,
            "missing": missing,
        }

    def create_draft(self, payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
        return self._request("POST", "/api/growth/news", json=payload, correlation_id=correlation_id).json()

    def update_draft(self, external_id: str, payload: dict[str, Any], *, correlation_id: str) -> dict[str, Any]:
        return self._request("PATCH", f"/api/growth/news/{external_id}", json=payload, correlation_id=correlation_id).json()

    def get_preview_url(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/growth/news/{external_id}/preview-url", correlation_id=correlation_id).json()

    def publish(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/growth/news/{external_id}/publish", correlation_id=correlation_id).json()

    def get_status(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/growth/news/{external_id}", correlation_id=correlation_id).json()

    def unpublish(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/growth/news/{external_id}/unpublish", correlation_id=correlation_id).json()

    def restore_previous(self, external_id: str, *, correlation_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/growth/news/{external_id}/restore-previous", correlation_id=correlation_id).json()

    def _request(self, method: str, path: str, *, correlation_id: str, **kwargs) -> httpx.Response:
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
                    raise RateLimitExceededError("Oling API rate limit reached.")
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
            except httpx.HTTPError as exc:
                last_error = exc
                self._record_failure(correlation_id, None)
                if attempt < attempts:
                    time.sleep(self.config.retry_backoff_seconds * attempt)
                    continue
                structured_log(
                    "oling.http_error",
                    correlation_id=correlation_id,
                    mode=self.config.mode,
                    error_type=exc.__class__.__name__,
                )
                incr("oling.http_error")
                raise ExternalConnectorError("Oling API request failed.") from exc
        raise ExternalConnectorError("Oling API request failed.") from last_error

    def _raise_http_error(self, response: httpx.Response, correlation_id: str) -> ExternalConnectorError:
        payload: dict[str, Any]
        try:
            payload = response.json()
        except Exception:
            payload = {"message": response.text[:300]}
        structured_log(
            "oling.api_error",
            correlation_id=correlation_id,
            mode=self.config.mode,
            status_code=response.status_code,
            message=payload.get("detail") or payload.get("message", ""),
        )
        incr("oling.api_error")
        if response.status_code == 429:
            return RateLimitExceededError("Oling API rate limit reached.")
        if response.status_code in {401, 403}:
            return ExternalConnectorError("Oling authentication is invalid.")
        if 400 <= response.status_code <= 499:
            return ExternalConnectorError(f"Oling API client error: {response.status_code}")
        return ExternalConnectorError(f"Oling API server error: {response.status_code}")

    def _breaker_state(self) -> dict[str, float | int | None]:
        key = self.config.base_url or "oling"
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
        structured_log("oling.circuit_open", correlation_id=correlation_id, mode=self.config.mode)
        incr("oling.circuit_open")
        raise ExternalConnectorError("Oling circuit breaker is open.")

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
            structured_log(
                "oling.circuit_opened",
                correlation_id=correlation_id,
                mode=self.config.mode,
                failures=failures,
                status_code=status_code,
            )
            incr("oling.circuit_opened")
