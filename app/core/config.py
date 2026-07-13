from functools import lru_cache

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./mapsi_growth_factory.db"
    test_database_url: str = "postgresql+psycopg://mapsi:mapsi@localhost:5433/mapsi_growth_factory_test"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "mapsi:growth:tasks"
    mapsi_api_key: str = "change-me"
    mapsi_growth_base_url: str = ""
    mapsi_growth_bearer_token: str = ""
    mapsi_growth_repository_full_name: str = "oling-mapsi/mapsi-v6"
    mapsi_growth_default_branch: str = "master"
    github_app_id: str = ""
    github_app_installation_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = "github-webhook-secret"
    github_allowed_repositories: str = "mapsi/mapsi-v6"
    github_api_url: str = "https://api.github.com"
    github_contract_path: str = "growth/change-notes"
    mapsi_instances: str = "instances: []"
    contact_hash_salt: str = "change-me-contact-salt"
    audience_segment_min_size: int = 1
    audience_segment_max_size: int = 10000
    contact_encryption_key: str = "change-me-contact-encryption-key"
    mautic_base_url: str = "http://localhost:8081"
    mautic_username: str = ""
    mautic_password: str = ""
    mautic_access_token: str = ""
    mautic_verify_tls: bool = True
    linkedin_mode: str = "mock"
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/ops/linkedin/oauth/callback"
    linkedin_company_id: str = "3347696"
    linkedin_organization_urn: str = ""
    linkedin_access_token: str = ""
    linkedin_refresh_token: str = ""
    linkedin_api_version: str = "202506"
    linkedin_scope: str = "openid profile email w_member_social rw_organization_admin w_organization_social r_organization_social"
    linkedin_verify_tls: bool = True
    mautic_category_name: str = "MAPSI Growth"
    mautic_weekly_template_name: str = "MAPSI Weekly Update"
    mautic_weekly_campaign_name: str = "MAPSI Weekly Nurture Disabled"
    editorial_engine_mode: str = "simulated"
    editorial_agent_backend: str = "simulated"
    editorial_agent_model: str = "gpt-4.1-mini"
    editorial_agent_temperature: float = 0.2
    editorial_generation_max_budget_tokens: int = 12000
    review_admin_username: str = "admin"
    review_admin_password: str = "change-me-review-password"
    review_sample_authorized_users: str = ""
    review_portal_mode: str = "enabled"
    review_portal_studio_url: str = "https://studio.mapsi.fr/growth"
    review_portal_emergency_allowlist: str = ""
    review_portal_emergency_key: str = "change-me-review-emergency-key"
    review_portal_emergency_banner: str = "Emergency access only. Use MAPSI Studio unless incident response requires this portal."
    review_token_ttl_minutes: int = 120
    review_token_max_uses: int = 20
    studio_admin_api_enabled: bool = False
    studio_admin_jwt_issuer: str = "mapsi-studio"
    studio_admin_jwt_audience: str = "mapsi-growth-admin"
    studio_admin_jwt_allowed_algorithms: str = "RS256"
    studio_admin_jwt_max_lifetime_seconds: int = 300
    studio_admin_jwt_leeway_seconds: int = 30
    studio_admin_jwt_public_keys: str = "keys: []"
    studio_admin_role_permissions: str = (
        "roles:\n"
        "  ROLE_GROWTH_VIEWER: [GROWTH_VIEW]\n"
        "  ROLE_GROWTH_REVIEW: [GROWTH_VIEW, GROWTH_REVIEW]\n"
        "  ROLE_GROWTH_APPROVE: [GROWTH_VIEW, GROWTH_REVIEW, GROWTH_APPROVE]\n"
        "  ROLE_GROWTH_PUBLISH: [GROWTH_VIEW, GROWTH_REVIEW, GROWTH_APPROVE, GROWTH_PUBLISH]\n"
        "  ROLE_GROWTH_CONFIGURE: [GROWTH_VIEW, GROWTH_CONFIGURE]\n"
        "  ROLE_GROWTH_AUDIT: [GROWTH_VIEW, GROWTH_AUDIT]\n"
        "  ROLE_SUPER_ADMIN: [GROWTH_VIEW, GROWTH_REVIEW, GROWTH_APPROVE, GROWTH_PUBLISH, GROWTH_CONFIGURE, GROWTH_AUDIT]\n"
    )
    studio_admin_enforce_replay_protection: bool = True
    studio_admin_allowed_ip_ranges: str = ""
    studio_admin_sensitive_confirmation_phrase: str = "CONFIRM"
    channel_operational_safe_default_enabled: bool = False
    growth_operation_mode: str = "safe"
    pilot_email_allowlist: str = ""
    workflow_kill_switch: bool = False
    publication_instance_kill_switches: str = ""
    publication_client_kill_switches: str = ""
    publish_oling_enabled: bool = False
    oling_mode: str = "mock"
    oling_base_url: str = "https://www.oling.fr"
    oling_site_base_url: str = "https://www.oling.fr"
    oling_api_token: str = ""
    oling_verify_tls: bool = True
    oling_timeout_seconds: float = 10.0
    oling_max_retries: int = 2
    oling_retry_backoff_seconds: float = 0.25
    oling_circuit_breaker_threshold: int = 3
    oling_circuit_breaker_reset_seconds: int = 60
    publish_mapsi_site_enabled: bool = False
    mapsi_site_mode: str = "mock"
    mapsi_site_base_url: str = "https://growth.mapseditor.invalid"
    mapsi_site_public_base_url: str = "https://www.mapsi.fr"
    mapsi_site_api_token: str = ""
    mapsi_site_verify_tls: bool = True
    mapsi_site_timeout_seconds: float = 10.0
    mapsi_site_max_retries: int = 2
    mapsi_site_retry_backoff_seconds: float = 0.25
    mapsi_site_circuit_breaker_threshold: int = 3
    mapsi_site_circuit_breaker_reset_seconds: int = 60
    publish_linkedin_enabled: bool = False
    send_mapsi_users_enabled: bool = False
    send_prospect_newsletter_enabled: bool = False
    publish_mapsi_studio_enabled: bool = False
    mailpit_base_url: str = "http://localhost:8025"
    adoption_alert_unsubscribe_rate: float = 0.03
    adoption_alert_bounce_rate: float = 0.02
    adoption_alert_deliverability_floor: float = 0.95
    adoption_alert_effect_floor: float = 0.01
    adoption_alert_error_rate: float = 0.05

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_mapsi_instances() -> list[dict]:
    payload = yaml.safe_load(get_settings().mapsi_instances) or {}
    return payload.get("instances", [])


def get_studio_admin_public_keys() -> list[dict]:
    payload = yaml.safe_load(get_settings().studio_admin_jwt_public_keys) or {}
    return payload.get("keys", [])


def get_studio_admin_role_permissions() -> dict[str, list[str]]:
    payload = yaml.safe_load(get_settings().studio_admin_role_permissions) or {}
    return payload.get("roles", {})


def get_pilot_email_allowlist() -> set[str]:
    return {item.strip().casefold() for item in get_settings().pilot_email_allowlist.split(",") if item.strip()}
