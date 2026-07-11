from app.application.ports.audit import AuditLogPort
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.ports.repositories import CampaignRepositoryPort
from app.domain.entities import Interaction
from app.domain.errors import CampaignNotFoundError


class TaskWorkerService:
    def __init__(
        self,
        repository: CampaignRepositoryPort,
        audit_log: AuditLogPort,
        github_intelligence: GitHubIntelligenceService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_log = audit_log
        self.github_intelligence = github_intelligence

    def handle(self, job: dict) -> None:
        task_name = job["task_name"]
        payload = job["payload"]
        if task_name == "github.weekly_backfill":
            if self.github_intelligence is not None:
                self.github_intelligence.run_weekly_backfill()
            return
        campaign = self.repository.get(payload["campaign_id"])
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {payload['campaign_id']} not found.")

        if task_name == "campaign.prepare_review_bundle":
            self.audit_log.append(campaign.id, "task.review_bundle_prepared", payload)
            return

        if task_name == "campaign.rework_assets":
            for asset in campaign.content_assets:
                if asset.revision <= payload.get("revision", 0):
                    asset.body = f"{asset.body}\n\nReworked revision {asset.revision}."
            self.repository.save(campaign)
            self.audit_log.append(campaign.id, "task.assets_reworked", payload)
            return

        if task_name == "campaign.notify_created":
            self.audit_log.append(campaign.id, "task.created_notification_sent", payload)
            return

        if task_name == "campaign.notify_approved":
            self.audit_log.append(campaign.id, "task.approval_notification_sent", payload)
            return

        if task_name == "campaign.archive_draft":
            self.audit_log.append(campaign.id, "task.draft_archived", payload)
            return

        if task_name == "campaign.refresh_publication_metrics":
            for channel in payload.get("channels", []):
                campaign.interactions.append(
                    Interaction(
                        campaign_run_id=campaign.id,
                        interaction_type="publication_metrics_refreshed",
                        metadata={"channel": channel},
                    )
                )
            self.repository.save(campaign)
            self.audit_log.append(campaign.id, "task.publication_metrics_refreshed", payload)
            return

        self.audit_log.append(campaign.id, "task.ignored", payload)
