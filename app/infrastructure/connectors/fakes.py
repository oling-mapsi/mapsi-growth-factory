from app.application.ports.connectors import (
    DolibarrConnectorPort,
    GitHubConnectorPort,
    LinkedInConnectorPort,
    MAPSIConnectorPort,
    MauticConnectorPort,
    MicrosoftGraphConnectorPort,
    OlingSiteConnectorPort,
)
from app.core.config import get_settings
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
                locale="fr-FR",
                title=f"{campaign.name} launch post",
                content_text=f"Hook: {campaign.objective} for {campaign.audience_segments[0].name}",
                audience_segment_id=campaign.audience_segments[0].id,
            ),
            ContentAsset(
                campaign_run_id=campaign.id,
                asset_type="oling_news_article",
                channel="oling",
                locale="fr-FR",
                title=f"{campaign.name} article",
                content_html=f"<p>Long-form article grounded on {campaign.objective}</p>",
                content_text=f"Long-form article grounded on {campaign.objective}",
                audience_segment_id=campaign.audience_segments[0].id,
            ),
            ContentAsset(
                campaign_run_id=campaign.id,
                asset_type="mapsi_user_email",
                channel="mautic",
                locale="fr-FR",
                title=f"{campaign.name} nurture email",
                subject=f"{campaign.name} nurture email",
                content_html=f"<p>Email sequence for {campaign.audience_segments[0].description}</p>",
                content_text=f"Email sequence for {campaign.audience_segments[0].description}",
                audience_segment_id=campaign.audience_segments[0].id,
            )
        ]
        for asset in assets:
            asset.content_hash = build_content_hash(
                asset.asset_type,
                asset.title,
                asset.body,
                asset.evidence_ids,
                asset.audience_segment_id,
                locale=asset.locale,
                subject=asset.subject,
                content_html=asset.content_html,
                content_text=asset.content_text,
                excerpt=asset.excerpt,
                call_to_action=asset.call_to_action,
                target_url=asset.target_url,
            )
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


class SimulatedPublisherMixin:
    feature_flag_name = ""
    external_prefix = "sandbox"
    external_base_url = "https://sandbox.invalid"

    def validate_configuration(self, channel: str) -> dict:
        enabled = bool(getattr(get_settings(), self.feature_flag_name)) if self.feature_flag_name else False
        return {"channel": channel, "enabled": enabled, "sandbox": True}

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "channel": asset.channel, "preview": asset.content_text}

    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel=asset.channel,
            external_reference=f"{self.external_prefix}:{asset.id}",
            external_url=f"{self.external_base_url}/{asset.id}",
        )

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return self.publish(campaign, asset)

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "status": "sandbox_published"}

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id}


class SimulatedLinkedInConnector(SimulatedPublisherMixin, LinkedInConnectorPort):
    feature_flag_name = "publish_linkedin_enabled"
    external_prefix = "linkedin"
    external_base_url = "https://sandbox.linkedin.example/posts"


class OlingMockPublisher(SimulatedPublisherMixin, OlingSiteConnectorPort):
    feature_flag_name = "publish_oling_enabled"
    external_prefix = "oling"
    external_base_url = "https://sandbox.oling.example/articles"


class SimulatedOlingSiteConnector(OlingMockPublisher):
    pass


class SimulatedMapsiSiteConnector(SimulatedPublisherMixin, OlingSiteConnectorPort):
    feature_flag_name = "publish_mapsi_site_enabled"
    external_prefix = "mapsi-site"
    external_base_url = "https://sandbox.mapsi.example/news"


class SimulatedMapsiStudioConnector(SimulatedPublisherMixin, OlingSiteConnectorPort):
    feature_flag_name = "publish_mapsi_studio_enabled"
    external_prefix = "mapsi-studio"
    external_base_url = "https://sandbox.mapsi.example/studio"


class SimulatedMapsiUsersConnector(SimulatedPublisherMixin, OlingSiteConnectorPort):
    feature_flag_name = "send_mapsi_users_enabled"
    external_prefix = "mapsi-users"
    external_base_url = "https://sandbox.mapsi.example/users"


class SimulatedProspectNewsletterConnector(SimulatedPublisherMixin, OlingSiteConnectorPort):
    feature_flag_name = "send_prospect_newsletter_enabled"
    external_prefix = "prospect-newsletter"
    external_base_url = "https://sandbox.mapsi.example/prospects"


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

    def _publisher_for(self, channel: str) -> LinkedInConnectorPort | OlingSiteConnectorPort:
        if channel not in self.publishers:
            raise ValueError(f"Unsupported publication channel: {channel}")
        return self.publishers[channel]

    def validate_configuration(self, channel: str) -> dict:
        return self._publisher_for(channel).validate_configuration(channel)

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return self._publisher_for(asset.channel).create_preview(campaign, asset)

    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return self._publisher_for(asset.channel).publish(campaign, asset)

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return self._publisher_for(asset.channel).update(campaign, asset)

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        return self._publisher_for(asset.channel).unpublish(campaign, asset)

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return self._publisher_for(asset.channel).get_publication_status(campaign, asset)

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return self._publisher_for(asset.channel).collect_metrics(campaign, asset)
