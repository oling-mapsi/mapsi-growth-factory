from abc import ABC, abstractmethod

from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, Publication, SourceEvidence


class CampaignGeneratorPort(ABC):
    @abstractmethod
    def generate_brief(self, campaign: CampaignRun) -> EditorialBrief:
        raise NotImplementedError

    @abstractmethod
    def generate_assets(self, campaign: CampaignRun) -> list[ContentAsset]:
        raise NotImplementedError

    @abstractmethod
    def collect_evidence(self, campaign: CampaignRun) -> list[SourceEvidence]:
        raise NotImplementedError


class PublisherPort(ABC):
    @abstractmethod
    def validate_configuration(self, channel: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        raise NotImplementedError

    @abstractmethod
    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        raise NotImplementedError

    @abstractmethod
    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        raise NotImplementedError

    @abstractmethod
    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        raise NotImplementedError

    @abstractmethod
    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        raise NotImplementedError


class GitHubConnectorPort(CampaignGeneratorPort, ABC):
    pass


class MAPSIConnectorPort(CampaignGeneratorPort, ABC):
    pass


class MicrosoftGraphConnectorPort(CampaignGeneratorPort, ABC):
    pass


class MauticConnectorPort(CampaignGeneratorPort, ABC):
    pass


class DolibarrConnectorPort(CampaignGeneratorPort, ABC):
    pass


class LinkedInConnectorPort(PublisherPort, ABC):
    pass


class OlingSiteConnectorPort(PublisherPort, ABC):
    pass
