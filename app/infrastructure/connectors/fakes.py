from app.application.ports.connectors import (
    DolibarrConnectorPort,
    GitHubConnectorPort,
    LinkedInConnectorPort,
    MAPSIConnectorPort,
    MauticConnectorPort,
    MicrosoftGraphConnectorPort,
    OlingSiteConnectorPort,
)
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, Publication, SourceEvidence, build_content_hash


class SimulatedGeneratorMixin:
    source_name = "simulated"

    def generate_brief(self, campaign: CampaignRun) -> EditorialBrief:
        return EditorialBrief(
            campaign_run_id=campaign.id,
            title=f"{campaign.name} brief",
            summary=f"Simulated brief for {campaign.objective}",
        )

    def generate_assets(self, campaign: CampaignRun) -> list[ContentAsset]:
        assets = [
            ContentAsset(
                campaign_run_id=campaign.id,
                asset_type="linkedin_company_post",
                channel="linkedin",
                title=f"{campaign.name} launch post",
                body=f"Hook: {campaign.objective} for {campaign.audience_segments[0].name}",
                audience_segment_id=campaign.audience_segments[0].id,
            ),
            ContentAsset(
                campaign_run_id=campaign.id,
                asset_type="website_article",
                channel="oling",
                title=f"{campaign.name} article",
                body=f"Long-form article grounded on {campaign.objective}",
                audience_segment_id=campaign.audience_segments[0].id,
            ),
            ContentAsset(
                campaign_run_id=campaign.id,
                asset_type="customer_email",
                channel="mautic",
                title=f"{campaign.name} nurture email",
                body=f"Email sequence for {campaign.audience_segments[0].description}",
                audience_segment_id=campaign.audience_segments[0].id,
            )
        ]
        for asset in assets:
            asset.content_hash = build_content_hash(asset.asset_type, asset.title, asset.body, asset.evidence_ids, asset.audience_segment_id)
        return assets

    def collect_evidence(self, campaign: CampaignRun) -> list[SourceEvidence]:
        return [
            SourceEvidence(
                campaign_run_id=campaign.id,
                source_system=self.source_name,
                reference=f"{self.source_name}:{campaign.id}",
            )
        ]


class SimulatedGitHubConnector(SimulatedGeneratorMixin, GitHubConnectorPort):
    source_name = "github"


class SimulatedMAPSIConnector(SimulatedGeneratorMixin, MAPSIConnectorPort):
    source_name = "mapsi"


class SimulatedMicrosoftGraphConnector(SimulatedGeneratorMixin, MicrosoftGraphConnectorPort):
    source_name = "microsoft_graph"


class SimulatedMauticConnector(SimulatedGeneratorMixin, MauticConnectorPort):
    source_name = "mautic"


class SimulatedDolibarrConnector(SimulatedGeneratorMixin, DolibarrConnectorPort):
    source_name = "dolibarr"


class SimulatedLinkedInConnector(LinkedInConnectorPort):
    def publish(self, campaign: CampaignRun, channel: str) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            channel=channel,
            external_reference=f"linkedin:{campaign.id}",
        )


class SimulatedOlingSiteConnector(OlingSiteConnectorPort):
    def publish(self, campaign: CampaignRun, channel: str) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            channel=channel,
            external_reference=f"oling:{campaign.id}",
        )


class CompositeSimulatedGenerator(SimulatedGeneratorMixin):
    def __init__(
        self,
        generators: list[
            GitHubConnectorPort
            | MAPSIConnectorPort
            | MicrosoftGraphConnectorPort
            | MauticConnectorPort
            | DolibarrConnectorPort
        ],
    ) -> None:
        self.generators = generators

    def collect_evidence(self, campaign: CampaignRun) -> list[SourceEvidence]:
        evidences: list[SourceEvidence] = []
        for generator in self.generators:
            evidences.extend(generator.collect_evidence(campaign))
        return evidences

    def generate_assets(self, campaign: CampaignRun) -> list[ContentAsset]:
        assets: list[ContentAsset] = []
        for generator in self.generators[:1]:
            assets.extend(generator.generate_assets(campaign))
        return assets


class CompositeSimulatedPublisher:
    def __init__(self, publishers: dict[str, LinkedInConnectorPort | OlingSiteConnectorPort]) -> None:
        self.publishers = publishers

    def publish(self, campaign: CampaignRun, channel: str) -> Publication:
        if channel not in self.publishers:
            raise ValueError(f"Unsupported publication channel: {channel}")
        return self.publishers[channel].publish(campaign, channel)
