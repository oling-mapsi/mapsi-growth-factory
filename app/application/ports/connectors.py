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
    def publish(self, campaign: CampaignRun, channel: str) -> Publication:
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
