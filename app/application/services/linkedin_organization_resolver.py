from __future__ import annotations

from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.infrastructure.connectors.linkedin import LinkedInConnector


class LinkedInOrganizationResolver:
    def __init__(self, connector: LinkedInConnector, oauth_service: LinkedInOAuthService) -> None:
        self.connector = connector
        self.oauth_service = oauth_service

    def resolve(self) -> dict[str, str]:
        token = self.oauth_service.get_valid_token()
        self.connector.config.access_token = token.access_token
        return self.connector.get_organization()
