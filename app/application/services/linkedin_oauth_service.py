from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from app.domain.entities import LinkedInOAuthToken, utcnow
from app.domain.errors import ExternalConnectorError
from app.infrastructure.connectors.linkedin import LinkedInConnector
from app.infrastructure.observability import structured_log
from app.infrastructure.repositories.linkedin import LinkedInOAuthTokenRepository


class LinkedInOAuthService:
    def __init__(self, connector: LinkedInConnector, repository: LinkedInOAuthTokenRepository) -> None:
        self.connector = connector
        self.repository = repository

    def build_authorization_url(self) -> dict[str, str]:
        state = token_urlsafe(24)
        return {"authorization_url": self.connector.build_authorization_url(state), "state": state}

    def exchange_code(self, code: str) -> LinkedInOAuthToken:
        payload = self.connector.exchange_code(code)
        token = self.repository.get() or LinkedInOAuthToken()
        token.access_token = payload["access_token"]
        token.refresh_token = payload["refresh_token"] or token.refresh_token
        token.scope = payload["scope"]
        token.expires_at = payload["expires_at"]
        token.refresh_expires_at = payload["refresh_expires_at"]
        token.updated_at = utcnow()
        structured_log("linkedin.oauth_token_exchanged", expires_at=token.expires_at, mode=self.connector.config.mode)
        return self.repository.save(token)

    def get_valid_token(self) -> LinkedInOAuthToken:
        token = self.repository.get()
        if token is None:
            if self.connector.config.access_token:
                now = datetime.now(UTC)
                token = LinkedInOAuthToken(
                    access_token=self.connector.config.access_token,
                    refresh_token=self.connector.config.refresh_token,
                    scope=self.connector.config.scope,
                    expires_at=now + timedelta(minutes=30),
                    refresh_expires_at=now + timedelta(days=30),
                )
                return self.repository.save(token)
            raise ExternalConnectorError("LinkedIn OAuth token is missing.")
        now = datetime.now(UTC)
        expires_at = self._utc(token.expires_at)
        refresh_expires_at = self._utc(token.refresh_expires_at)
        token.expires_at = expires_at
        token.refresh_expires_at = refresh_expires_at
        if expires_at and expires_at <= now + timedelta(minutes=5):
            if not token.refresh_token:
                raise ExternalConnectorError("LinkedIn OAuth token expired and cannot be refreshed.")
            payload = self.connector.refresh_token(token.refresh_token)
            token.access_token = payload["access_token"]
            token.refresh_token = payload["refresh_token"] or token.refresh_token
            token.scope = payload["scope"]
            token.expires_at = payload["expires_at"]
            token.refresh_expires_at = payload["refresh_expires_at"] or token.refresh_expires_at
            token.updated_at = utcnow()
            token = self.repository.save(token)
            structured_log("linkedin.oauth_token_refreshed", expires_at=token.expires_at, mode=self.connector.config.mode)
        return token

    def _utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
