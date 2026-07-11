from __future__ import annotations

from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.infrastructure.connectors.linkedin import LinkedInConnector


class LinkedInMediaUploader:
    def __init__(
        self,
        connector: LinkedInConnector,
        oauth_service: LinkedInOAuthService,
        organization_resolver: LinkedInOrganizationResolver,
    ) -> None:
        self.connector = connector
        self.oauth_service = oauth_service
        self.organization_resolver = organization_resolver

    def upload_image(self, content: bytes, content_type: str = "image/png") -> str:
        token = self.oauth_service.get_valid_token()
        self.connector.config.access_token = token.access_token
        organization = self.organization_resolver.resolve()
        payload = self.connector.initialize_image_upload(organization["urn"])
        self.connector.upload_media(payload["upload_url"], content, content_type)
        return payload["image_urn"]
