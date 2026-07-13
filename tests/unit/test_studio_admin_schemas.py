from app.entrypoints.api.admin_schemas import StudioAdminAssetResponse, StudioAdminAuditEventResponse, StudioAdminChannelResponse, StudioAdminGlobalKillSwitchResponse, StudioAdminPublicationOperationResponse, StudioAdminPublicationResponse


def test_studio_admin_asset_schema_stays_sanitized() -> None:
    payload = StudioAdminAssetResponse(
        id="asset-1",
        campaign_id="camp-1",
        campaign_title="Campaign",
        channel="oling",
        asset_type="website_article",
        title="Title",
        status="PUBLISHED",
        version=1,
        content_hash="hash",
        approved_content_hash="approved-hash",
        quality={"passed": True},
        approval={"status": "approved", "approved_by": "admin", "approved_at": None},
        preview_available=True,
        publication_available=True,
        public_url="https://example.test/article",
        last_error_message="",
        published_at=None,
        created_at="2026-07-12T11:00:00Z",
    ).model_dump(mode="json")

    assert "content_html" not in payload
    assert "content_text" not in payload
    assert "body" not in payload
    assert "results" not in payload
    assert "email" not in str(payload).lower()


def test_studio_admin_publication_schema_exposes_business_fields_only() -> None:
    payload = StudioAdminPublicationResponse(
        asset_id="asset-1",
        available=True,
        publisher_type="oling_api",
        publication_mode_requested="publish",
        publication_mode_executed="live",
        publication_status="PUBLISHED",
        external_publication_id="asset-1",
        external_publication_url="https://example.test/article",
        idempotency_key="idem-1",
        published_at=None,
        metadata={"published_revision_number": 1},
    ).model_dump(mode="json")

    assert "token" not in str(payload).lower()
    assert "password" not in str(payload).lower()
    assert payload["publication_status"] == "PUBLISHED"


def test_studio_admin_publication_operation_schema_exposes_controlled_error_fields_only() -> None:
    payload = StudioAdminPublicationOperationResponse(
        operation_id="op-1",
        asset_id="asset-1",
        channel="oling",
        requested_action="publish",
        status="published",
        publisher="oling_api",
        external_id="asset-1",
        preview_url="https://preview.example.test/a1",
        public_url="https://example.test/article",
        scheduled_at=None,
        published_at=None,
        error_code="",
        error_message="",
        retryable=False,
        correlation_id="corr-1",
        metadata={"publication_status": "PUBLISHED"},
    ).model_dump(mode="json")

    assert "token" not in str(payload).lower()
    assert payload["requested_action"] == "publish"


def test_studio_admin_channel_schema_exposes_operational_state_without_credentials() -> None:
    payload = StudioAdminChannelResponse(
        key="oling",
        label="Oling",
        asset_types=["website_article"],
        supports_preview=True,
        supports_publication=True,
        enabled=True,
        configured=True,
        credentials_valid=True,
        feature_enabled=True,
        emergency_kill_switch=False,
        sandbox_available=True,
        real_publisher_available=True,
        last_health_check=None,
        last_successful_publication=None,
        last_error="",
        updated_by="studio-user-1",
        updated_at=None,
        activation_expires_at=None,
        operational_mode="pilot",
        banner_message="MODE PILOTE",
    ).model_dump(mode="json")

    assert "token" not in str(payload).lower()
    assert "password" not in str(payload).lower()
    assert payload["real_publisher_available"] is True
    assert payload["operational_mode"] == "pilot"


def test_studio_admin_global_kill_switch_schema_stays_minimal() -> None:
    payload = StudioAdminGlobalKillSwitchResponse(
        active=False,
        updated_by="studio-user-1",
        updated_at=None,
    ).model_dump(mode="json")

    assert list(payload) == ["active", "updated_by", "updated_at"]


def test_studio_admin_audit_event_schema_stays_controlled() -> None:
    payload = StudioAdminAuditEventResponse(
        event_id="evt-1",
        campaign_id="camp-1",
        asset_id="asset-1",
        actor_id="studio-user-1",
        actor_source="mapsi-studio",
        actor_roles=["ROLE_GROWTH_AUDIT"],
        event_type="publication.published",
        timestamp="2026-07-12T11:00:00Z",
        correlation_id="corr-1",
        idempotency_key="idem-1",
        previous_state={"status": "APPROVED"},
        new_state={"status": "PUBLISHED"},
        metadata={"external_id": "oling-42"},
        result="SUCCESS",
        channel="oling",
        source_ip="10.0.0.1",
        integrity_hash="abc",
        previous_integrity_hash="",
        integrity_ok=True,
    ).model_dump(mode="json")

    assert "token" not in str(payload).lower()
    assert "password" not in str(payload).lower()
    assert payload["integrity_ok"] is True
