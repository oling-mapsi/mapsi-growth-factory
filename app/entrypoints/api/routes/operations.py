from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.application.dto import PublishCampaignCommand
from app.application.ports.idempotency import IdempotencyStorePort
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.campaign_service import CampaignService
from app.application.services.adoption_measurement_service import AdoptionMeasurementService
from app.application.services.mapsi_product_changes_service import MapsiProductChangesService
from app.application.services.linkedin_metrics_collector import LinkedInMetricsCollector
from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.application.services.mapsi_usage_collection_service import MapsiUsageCollectionService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.review_portal_service import ReviewPortalService
from app.application.services.task_worker_service import TaskWorkerService
from app.application.services.weekly_campaign_generation_service import WeeklyCampaignGenerationService
from app.core.db import get_db_session
from app.core.security import verify_mapsi_api_key
from app.domain.errors import (
    CampaignNotFoundError,
    CampaignPublicationForbiddenError,
    DomainError,
    DuplicateCampaignPublicationError,
    EditorialGenerationBlockedError,
    EmergencyStopActiveError,
)
from app.entrypoints.api.dependencies import (
    get_campaign_service,
    get_campaign_publisher_service,
    get_mapsi_product_changes_service,
    get_adoption_measurement_service,
    get_mapsi_usage_collection_services,
    get_linkedin_metrics_collector,
    get_linkedin_oauth_service,
    get_linkedin_organization_resolver,
    get_linkedin_post_publisher,
    get_mautic_contact_sync_service,
    get_review_portal_service,
    get_task_worker_service,
    get_weekly_campaign_generation_service,
)
from app.entrypoints.api.idempotency import resolve_idempotent_response, store_idempotent_response
from app.entrypoints.api.routes.campaigns import get_idempotency_store
from app.entrypoints.api.schemas import (
    CollectMapsiUsageRequest,
    FailureNotificationRequest,
    LinkedInAssetPublishRequest,
    LinkedInOAuthExchangeRequest,
    MauticPublicationRequest,
    PublishApprovedCampaignRequest,
    RequestApprovalRequest,
    WorkflowCommandRequest,
    WorkflowOperationResponse,
)
from app.infrastructure.observability import structured_log

router = APIRouter(prefix="/ops", tags=["operations"], dependencies=[Depends(verify_mapsi_api_key)])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (CampaignPublicationForbiddenError, EditorialGenerationBlockedError, EmergencyStopActiveError, DuplicateCampaignPublicationError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _store(
    request: Request,
    key: str | None,
    payload: dict,
    response: WorkflowOperationResponse,
    store: IdempotencyStorePort,
    response_status: int = 200,
) -> WorkflowOperationResponse:
    store_idempotent_response(request, key, payload, response_status, jsonable_encoder(response), store)
    return response


@router.post("/collect-product-changes", response_model=WorkflowOperationResponse)
def collect_product_changes(
    request: Request,
    payload: WorkflowCommandRequest,
    service: MapsiProductChangesService = Depends(get_mapsi_product_changes_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    count = service.collect(dry_run=payload.dry_run)
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(
            correlation_id=payload.correlation_id,
            status="completed",
            details={"product_changes_collected": count, "dry_run": payload.dry_run},
        ),
        store,
    )


@router.post("/collect-mapsi-usage", response_model=WorkflowOperationResponse)
def collect_mapsi_usage(
    request: Request,
    payload: CollectMapsiUsageRequest,
    services: dict[str, MapsiUsageCollectionService] = Depends(get_mapsi_usage_collection_services),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    target_ids = [payload.instance_id] if payload.instance_id else sorted(services.keys())
    reports: dict[str, dict] = {}
    for instance_id in target_ids:
        service = services.get(instance_id)
        if service is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown MAPSI instance: {instance_id}")
        reports[instance_id] = service.collect(dry_run=payload.dry_run)
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details={"instances": reports}),
        store,
    )


@router.post("/sync-mautic-contacts", response_model=WorkflowOperationResponse)
def sync_mautic_contacts(
    request: Request,
    payload: WorkflowCommandRequest,
    service: MauticContactSyncService = Depends(get_mautic_contact_sync_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    report = service.sync_contacts(dry_run=payload.dry_run)
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details=report),
        store,
    )


@router.post("/generate-weekly-campaign", response_model=WorkflowOperationResponse)
def generate_weekly_campaign(
    request: Request,
    payload: WorkflowCommandRequest,
    service: WeeklyCampaignGenerationService = Depends(get_weekly_campaign_generation_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        result = service.generate(dry_run=payload.dry_run)
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details=result),
        store,
    )


@router.post("/campaigns/{campaign_id}/request-approval", response_model=WorkflowOperationResponse)
def request_approval(
    request: Request,
    campaign_id: str,
    payload: RequestApprovalRequest,
    service: ReviewPortalService = Depends(get_review_portal_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        review, token = service.prepare_review(campaign_id, proposed_at=payload.proposed_at)
    except DomainError as exc:
        raise _error(exc) from exc
    response = WorkflowOperationResponse(
        correlation_id=payload.correlation_id,
        status="pending_approval",
        details={
            "campaign_id": campaign_id,
            "review_id": review.id,
            "review_url": f"/review/{token}",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=service.settings.review_token_ttl_minutes)).isoformat(),
        },
    )
    return _store(request, idempotency_key, body, response, store)


@router.get("/campaigns/{campaign_id}/review-status", response_model=WorkflowOperationResponse)
def review_status(
    campaign_id: str,
    correlation_id: str,
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> WorkflowOperationResponse:
    try:
        return WorkflowOperationResponse(
            correlation_id=correlation_id,
            status="completed",
            details=service.review_status(campaign_id),
        )
    except DomainError as exc:
        raise _error(exc) from exc


@router.get("/campaigns/{campaign_id}/publication-readiness", response_model=WorkflowOperationResponse)
def publication_readiness(
    campaign_id: str,
    correlation_id: str,
    scheduled_at: datetime | None = None,
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> WorkflowOperationResponse:
    try:
        return WorkflowOperationResponse(
            correlation_id=correlation_id,
            status="completed",
            details=service.publication_readiness(campaign_id, scheduled_at=scheduled_at),
        )
    except DomainError as exc:
        raise _error(exc) from exc


@router.post("/campaigns/{campaign_id}/publish-approved", response_model=WorkflowOperationResponse)
def publish_approved_campaign(
    request: Request,
    campaign_id: str,
    payload: PublishApprovedCampaignRequest,
    campaign_service: CampaignService = Depends(get_campaign_service),
    review_service: ReviewPortalService = Depends(get_review_portal_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    readiness = review_service.publication_readiness(campaign_id, scheduled_at=payload.scheduled_at)
    if not readiness["publishable"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Campaign is not publishable.")
    try:
        campaign = campaign_service.publish(campaign_id, PublishCampaignCommand(channels=payload.channels))
    except DomainError as exc:
        raise _error(exc) from exc
    response = WorkflowOperationResponse(
        correlation_id=payload.correlation_id,
        status="completed",
        details={
            "campaign_id": campaign.id,
            "status": campaign.status.value,
            "published_channels": [item.channel for item in campaign.publications],
            "scheduled_at": payload.scheduled_at,
        },
    )
    return _store(request, idempotency_key, body, response, store)


@router.post("/campaigns/{campaign_id}/mautic-preview", response_model=WorkflowOperationResponse)
def create_mautic_preview(
    request: Request,
    campaign_id: str,
    payload: MauticPublicationRequest,
    service: CampaignPublisher = Depends(get_campaign_publisher_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        details = service.create_preview(campaign_id, idempotency_key=idempotency_key or "")
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="preview_ready", details=details),
        store,
    )


@router.post("/campaigns/{campaign_id}/mautic-schedule", response_model=WorkflowOperationResponse)
def schedule_mautic_campaign(
    request: Request,
    campaign_id: str,
    payload: MauticPublicationRequest,
    service: CampaignPublisher = Depends(get_campaign_publisher_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    if payload.scheduled_at is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="scheduled_at is required.")
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        details = service.schedule_campaign(campaign_id, scheduled_at=payload.scheduled_at, idempotency_key=idempotency_key or "")
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="scheduled", details=details),
        store,
    )


@router.get("/linkedin/oauth/authorization-url", response_model=WorkflowOperationResponse)
def linkedin_authorization_url(
    correlation_id: str,
    service: LinkedInOAuthService = Depends(get_linkedin_oauth_service),
) -> WorkflowOperationResponse:
    return WorkflowOperationResponse(correlation_id=correlation_id, status="completed", details=service.build_authorization_url())


@router.post("/linkedin/oauth/exchange", response_model=WorkflowOperationResponse)
def linkedin_exchange_oauth_code(
    request: Request,
    payload: LinkedInOAuthExchangeRequest,
    service: LinkedInOAuthService = Depends(get_linkedin_oauth_service),
    resolver: LinkedInOrganizationResolver = Depends(get_linkedin_organization_resolver),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        token = service.exchange_code(payload.code)
        organization = resolver.resolve()
    except DomainError as exc:
        raise _error(exc) from exc
    response = WorkflowOperationResponse(
        correlation_id=payload.correlation_id,
        status="completed",
        details={
            "organization": organization,
            "token_expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "refresh_expires_at": token.refresh_expires_at.isoformat() if token.refresh_expires_at else None,
        },
    )
    return _store(request, idempotency_key, body, response, store)


@router.post("/campaigns/{campaign_id}/linkedin-publish", response_model=WorkflowOperationResponse)
def publish_linkedin_asset(
    request: Request,
    campaign_id: str,
    payload: LinkedInAssetPublishRequest,
    service: LinkedInPostPublisher = Depends(get_linkedin_post_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        details = service.publish_asset(campaign_id, payload.asset_id, idempotency_key=idempotency_key or "")
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details=details),
        store,
    )


@router.post("/campaigns/{campaign_id}/linkedin-metrics", response_model=WorkflowOperationResponse)
def collect_linkedin_metrics(
    request: Request,
    campaign_id: str,
    payload: WorkflowCommandRequest,
    service: LinkedInMetricsCollector = Depends(get_linkedin_metrics_collector),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        details = {"campaign_id": campaign_id, "collected": 0} if payload.dry_run else service.collect(campaign_id)
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details=details),
        store,
    )


@router.post("/campaigns/{campaign_id}/collect-metrics", response_model=WorkflowOperationResponse)
def collect_campaign_metrics(
    request: Request,
    campaign_id: str,
    payload: WorkflowCommandRequest,
    campaign_service: CampaignService = Depends(get_campaign_service),
    worker: TaskWorkerService = Depends(get_task_worker_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        campaign = campaign_service.get_campaign(campaign_id)
    except DomainError as exc:
        raise _error(exc) from exc
    channels = [item.channel for item in campaign.publications]
    if not payload.dry_run:
        worker.handle(
            {
                "task_name": "campaign.refresh_publication_metrics",
                "payload": {"campaign_id": campaign_id, "channels": channels},
            }
        )
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(
            correlation_id=payload.correlation_id,
            status="completed",
            details={"campaign_id": campaign_id, "channels": channels, "dry_run": payload.dry_run},
        ),
        store,
    )


@router.post("/campaigns/{campaign_id}/collect-adoption-metrics", response_model=WorkflowOperationResponse)
def collect_adoption_metrics(
    request: Request,
    campaign_id: str,
    payload: WorkflowCommandRequest,
    service: AdoptionMeasurementService = Depends(get_adoption_measurement_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        details = service.import_events(campaign_id) if not payload.dry_run else {"imported": 0, "skipped": 0}
    except DomainError as exc:
        raise _error(exc) from exc
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(correlation_id=payload.correlation_id, status="completed", details=details),
        store,
    )


@router.get("/campaigns/{campaign_id}/adoption-report", response_model=WorkflowOperationResponse)
def adoption_report(
    campaign_id: str,
    correlation_id: str,
    service: AdoptionMeasurementService = Depends(get_adoption_measurement_service),
) -> WorkflowOperationResponse:
    try:
        details = service.build_report(campaign_id)
    except DomainError as exc:
        raise _error(exc) from exc
    return WorkflowOperationResponse(correlation_id=correlation_id, status="completed", details=details)


@router.get("/reports/adoption-weekly", response_model=WorkflowOperationResponse)
def weekly_adoption_report(
    correlation_id: str,
    service: AdoptionMeasurementService = Depends(get_adoption_measurement_service),
) -> WorkflowOperationResponse:
    return WorkflowOperationResponse(correlation_id=correlation_id, status="completed", details=service.build_weekly_report())


@router.post("/failure-notifications", response_model=WorkflowOperationResponse)
def notify_failure(
    request: Request,
    payload: FailureNotificationRequest,
    session: Session = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> WorkflowOperationResponse:
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    structured_log(
        "workflow.failure_notification",
        correlation_id=payload.correlation_id,
        workflow=payload.workflow,
        step=payload.step,
        retryable=payload.retryable,
    )
    if payload.error and session:
        session.rollback()
    return _store(
        request,
        idempotency_key,
        body,
        WorkflowOperationResponse(
            correlation_id=payload.correlation_id,
            status="accepted",
            details={"workflow": payload.workflow, "step": payload.step, "retryable": payload.retryable},
        ),
        store,
    )
