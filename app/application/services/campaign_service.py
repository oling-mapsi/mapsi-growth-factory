from app.application.dto import CreateCampaignCommand, PublishCampaignCommand, ReviewCampaignCommand
from app.application.ports.audit import AuditLogPort
from app.application.ports.connectors import CampaignGeneratorPort, PublisherPort
from app.application.ports.repositories import CampaignRepositoryPort
from app.application.ports.tasks import TaskQueuePort
from app.application.services.review_portal_service import ReviewPortalService
from app.domain.entities import AudienceSegment, CampaignRun
from app.domain.enums import AssetStatus
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError


class CampaignService:
    def __init__(
        self,
        repository: CampaignRepositoryPort,
        generator: CampaignGeneratorPort,
        publisher: PublisherPort,
        audit_log: AuditLogPort,
        task_queue: TaskQueuePort,
        review_portal: ReviewPortalService | None = None,
    ) -> None:
        self.repository = repository
        self.generator = generator
        self.publisher = publisher
        self.audit_log = audit_log
        self.task_queue = task_queue
        self.review_portal = review_portal

    def create_campaign(self, command: CreateCampaignCommand) -> CampaignRun:
        campaign = CampaignRun(name=command.name, objective=command.objective)
        segment = AudienceSegment(
            campaign_run_id=campaign.id,
            name=command.audience_name,
            description=command.audience_description,
        )
        campaign.audience_segments.append(segment)
        saved = self.repository.add(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.created",
            {"objective": saved.objective, "audience_segment_id": segment.id},
            actor_source="system",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue("campaign.notify_created", {"campaign_id": saved.id})
        return saved

    def list_campaigns(self) -> list[CampaignRun]:
        return self.repository.list()

    def get_campaign(self, campaign_id: str) -> CampaignRun:
        campaign = self.repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        return campaign

    def generate_campaign(self, campaign_id: str) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        brief = self.generator.generate_brief(campaign)
        assets = self.generator.generate_assets(campaign)
        evidence = self.generator.collect_evidence(campaign)
        campaign.mark_generated(brief, assets)
        campaign.source_evidences.extend(evidence)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.generated",
            {"assets": len(saved.content_assets), "evidence_count": len(saved.source_evidences)},
            actor_source="system",
            previous_state={"status": "DRAFT"},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue(
            "campaign.prepare_review_bundle",
            {"campaign_id": saved.id, "asset_count": len(saved.content_assets)},
        )
        return saved

    def request_changes(self, campaign_id: str, command: ReviewCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        previous_status = campaign.status.value
        decision = campaign.request_changes(command.comment, command.decided_by)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.changes_requested",
            {"decision_id": decision.id},
            actor_id=command.decided_by,
            actor_source="review_portal",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue(
            "campaign.rework_assets",
            {"campaign_id": saved.id, "revision": max(asset.revision for asset in saved.content_assets)},
        )
        return saved

    def approve(self, campaign_id: str, command: ReviewCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        previous_status = campaign.status.value
        decision = campaign.approve(command.comment, command.decided_by)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.approved",
            {"decision_id": decision.id},
            actor_id=command.decided_by,
            actor_source="review_portal",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue("campaign.notify_approved", {"campaign_id": saved.id})
        return saved

    def reject(self, campaign_id: str, command: ReviewCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        previous_status = campaign.status.value
        decision = campaign.reject(command.comment, command.decided_by)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.rejected",
            {"decision_id": decision.id},
            actor_id=command.decided_by,
            actor_source="review_portal",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue("campaign.archive_draft", {"campaign_id": saved.id})
        return saved

    def publish(self, campaign_id: str, command: PublishCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        previous_status = campaign.status.value
        if self.review_portal is not None:
            self.review_portal.ensure_publishable(campaign_id)
        for channel in command.channels:
            assets = [
                asset
                for asset in campaign.content_assets
                if asset.channel == channel and asset.status in {AssetStatus.APPROVED, AssetStatus.FAILED}
            ]
            if not assets:
                raise CampaignPublicationForbiddenError(
                    f"Campaign {campaign.id} has no APPROVED assets for channel {channel}."
                )
            for asset in assets:
                publication = self.publisher.publish(campaign, asset)
                campaign.publish(publication)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "campaign.published",
            {"channels": command.channels, "publication_count": len(saved.publications)},
            actor_source="system",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        self.task_queue.enqueue(
            "campaign.refresh_publication_metrics",
            {"campaign_id": saved.id, "channels": command.channels},
        )
        return saved
