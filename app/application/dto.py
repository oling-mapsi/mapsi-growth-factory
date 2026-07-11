from dataclasses import dataclass


@dataclass
class CreateCampaignCommand:
    name: str
    objective: str
    audience_name: str
    audience_description: str


@dataclass
class ReviewCampaignCommand:
    decided_by: str
    comment: str = ""


@dataclass
class PublishCampaignCommand:
    channels: list[str]
