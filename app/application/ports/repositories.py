from abc import ABC, abstractmethod

from app.domain.entities import CampaignRun


class CampaignRepositoryPort(ABC):
    @abstractmethod
    def add(self, campaign: CampaignRun) -> CampaignRun:
        raise NotImplementedError

    @abstractmethod
    def get(self, campaign_id: str) -> CampaignRun | None:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[CampaignRun]:
        raise NotImplementedError

    @abstractmethod
    def save(self, campaign: CampaignRun) -> CampaignRun:
        raise NotImplementedError
