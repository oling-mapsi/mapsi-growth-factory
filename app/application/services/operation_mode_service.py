from __future__ import annotations

from app.core.config import get_pilot_email_allowlist, get_settings
from app.domain.errors import CampaignPublicationForbiddenError


class OperationModeService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def current_mode(self) -> str:
        mode = (self.settings.growth_operation_mode or "safe").strip().lower()
        return mode if mode in {"safe", "pilot"} else "safe"

    def is_pilot(self) -> bool:
        return self.current_mode() == "pilot"

    def banner_message(self) -> str:
        return "MODE PILOTE" if self.is_pilot() else ""

    def pilot_email_allowlist(self) -> set[str]:
        return get_pilot_email_allowlist()

    def is_email_allowlisted(self, email: str) -> bool:
        normalized = email.strip().casefold()
        return normalized != "" and normalized in self.pilot_email_allowlist()

    def assert_linkedin_real_publication_allowed(self) -> None:
        if self.is_pilot():
            raise CampaignPublicationForbiddenError("LinkedIn real publication is disabled in pilot mode. Draft only.")

    def assert_real_mapsi_users_audience_disabled(self) -> None:
        if self.is_pilot():
            raise CampaignPublicationForbiddenError("Pilot mode forbids any real MAPSI users audience publication. Use preview or allowlist-only test flows.")

    def assert_email_allowlisted(self, email: str) -> None:
        if not self.is_pilot():
            return
        if not self.is_email_allowlisted(email):
            raise CampaignPublicationForbiddenError(f"Pilot mode refuses email outside PILOT_EMAIL_ALLOWLIST: {email}.")

    def safe_mode_global_kill_switch_target(self) -> bool:
        return True

    def safe_mode_channels(self) -> tuple[str, ...]:
        return ("oling", "mapsi_site", "linkedin", "mapsi_users", "prospect_newsletter", "mautic")
