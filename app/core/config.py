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
    editorial_agent_backend: str = "simulated"
    editorial_agent_model: str = "gpt-4.1-mini"
    editorial_agent_temperature: float = 0.2
    review_admin_username: str = "admin"
    review_admin_password: str = "change-me-review-password"
    review_sample_authorized_users: str = ""
    review_token_ttl_minutes: int = 120
    review_token_max_uses: int = 20
    workflow_kill_switch: bool = False
    publication_instance_kill_switches: str = ""
    publication_client_kill_switches: str = ""
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
