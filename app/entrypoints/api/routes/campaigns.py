from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.application.dto import CreateCampaignCommand, PublishCampaignCommand, ReviewCampaignCommand
from app.application.ports.idempotency import IdempotencyStorePort
from app.application.services.campaign_service import CampaignService
from app.core.db import get_db_session
from app.core.security import verify_mapsi_api_key
from app.domain.errors import (
    ApprovalPrerequisiteError,
    CampaignNotFoundError,
    CampaignPublicationForbiddenError,
    DomainError,
)
from app.entrypoints.api.dependencies import get_campaign_service
from app.entrypoints.api.idempotency import resolve_idempotent_response, store_idempotent_response
from app.entrypoints.api.schemas import (
    CampaignResponse,
    CreateCampaignRequest,
    PublishRequest,
    ReviewRequest,
)
from app.infrastructure.repositories.idempotency import SqlAlchemyIdempotencyRepository

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[Depends(verify_mapsi_api_key)])


def get_idempotency_store(session: Session = Depends(get_db_session)) -> IdempotencyStorePort:
    return SqlAlchemyIdempotencyRepository(session)


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CampaignPublicationForbiddenError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ApprovalPrerequisiteError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    request: Request,
    payload: CreateCampaignRequest,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    cached = resolve_idempotent_response(request, idempotency_key, payload.model_dump(), store)
    if cached is not None:
        return cached
    campaign = service.create_campaign(
        CreateCampaignCommand(
            name=payload.name,
            objective=payload.objective,
            audience_name=payload.audience.name,
            audience_description=payload.audience.description,
        )
    )
    response = CampaignResponse.from_entity(campaign)
    store_idempotent_response(request, idempotency_key, payload.model_dump(), 201, jsonable_encoder(response), store)
    return response


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(service: CampaignService = Depends(get_campaign_service)) -> list[CampaignResponse]:
    return [CampaignResponse.from_entity(item) for item in service.list_campaigns()]


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: str, service: CampaignService = Depends(get_campaign_service)) -> CampaignResponse:
    try:
        return CampaignResponse.from_entity(service.get_campaign(campaign_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{campaign_id}/generate", response_model=CampaignResponse)
def generate_campaign(
    request: Request,
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    body = {"campaign_id": campaign_id}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        response = CampaignResponse.from_entity(service.generate_campaign(campaign_id))
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(response), store)
        return response
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{campaign_id}/request-changes", response_model=CampaignResponse)
def request_changes(
    request: Request,
    campaign_id: str,
    payload: ReviewRequest,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        response = CampaignResponse.from_entity(
            service.request_changes(
                campaign_id,
                ReviewCampaignCommand(decided_by=payload.decided_by, comment=payload.comment),
            )
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(response), store)
        return response
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{campaign_id}/approve", response_model=CampaignResponse)
def approve_campaign(
    request: Request,
    campaign_id: str,
    payload: ReviewRequest,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        response = CampaignResponse.from_entity(
            service.approve(
                campaign_id,
                ReviewCampaignCommand(decided_by=payload.decided_by, comment=payload.comment),
            )
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(response), store)
        return response
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{campaign_id}/reject", response_model=CampaignResponse)
def reject_campaign(
    request: Request,
    campaign_id: str,
    payload: ReviewRequest,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    body = {"campaign_id": campaign_id, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        response = CampaignResponse.from_entity(
            service.reject(
                campaign_id,
                ReviewCampaignCommand(decided_by=payload.decided_by, comment=payload.comment),
            )
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(response), store)
        return response
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{campaign_id}/publish", response_model=CampaignResponse)
def publish_campaign(
    request: Request,
    campaign_id: str,
    payload: PublishRequest,
    service: CampaignService = Depends(get_campaign_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
) -> CampaignResponse:
    body = {"campaign_id": campaign_id, "channels": payload.resolved_channels()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        response = CampaignResponse.from_entity(
            service.publish(
                campaign_id,
                PublishCampaignCommand(channels=payload.resolved_channels()),
            )
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(response), store)
        return response
    except DomainError as exc:
        raise _to_http_error(exc) from exc
