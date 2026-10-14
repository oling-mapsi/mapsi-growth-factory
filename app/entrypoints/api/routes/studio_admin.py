from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder

from app.application.services.studio_admin_service import StudioAdminService
from app.core.security import GROWTH_APPROVE, GROWTH_AUDIT, GROWTH_CONFIGURE, GROWTH_PUBLISH, GROWTH_REVIEW, GROWTH_VIEW, StudioAdminPrincipal, require_studio_admin_permission, sha256_hexdigest
from app.domain.errors import CampaignNotFoundError, DomainError, EditorialSourceItemNotFoundError, EditorialSourcePackNotFoundError, OptimisticLockError, WeeklyCommunicationPackNotFoundError
from app.entrypoints.api.dependencies import get_studio_admin_service
from app.entrypoints.api.idempotency import resolve_idempotent_response, store_idempotent_response
from app.entrypoints.api.routes.campaigns import get_idempotency_store
from app.entrypoints.api.admin_schemas import (
    StudioAdminAssetEnvelope,
    StudioAdminAssetListEnvelope,
    StudioAdminAssetCommentDecisionRequest,
    StudioAdminAssetDecisionRequest,
    StudioAdminAssetDraftUpdateRequest,
    StudioAdminAssetResponse,
    StudioAdminAssetVersionListEnvelope,
    StudioAdminAssetVersionResponse,
    StudioAdminAuditEventListEnvelope,
    StudioAdminAuditEventResponse,
    StudioAdminBulkCommentDecisionRequest,
    StudioAdminBulkDecisionEnvelope,
    StudioAdminBulkDecisionRequest,
    StudioAdminBulkDecisionResponse,
    StudioAdminCampaignEnvelope,
    StudioAdminCampaignListEnvelope,
    StudioAdminCampaignResponse,
    StudioAdminChannelEnvelope,
    StudioAdminChannelMutationRequest,
    StudioAdminChannelListEnvelope,
    StudioAdminChannelResponse,
    StudioAdminDashboardEnvelope,
    StudioAdminDashboardResponse,
    StudioAdminEditorialSourcePackEnvelope,
    StudioAdminEditorialSourcePackResponse,
    StudioAdminEditorialSourcePreviewEnvelope,
    StudioAdminEditorialSourcePreviewResponse,
    StudioAdminErrorResponse,
    StudioAdminEvidenceListEnvelope,
    StudioAdminEvidenceResponse,
    StudioAdminGlobalKillSwitchEnvelope,
    StudioAdminGlobalKillSwitchResponse,
    StudioAdminHealthEnvelope,
    StudioAdminHealthResponse,
    StudioAdminPaginationResponse,
    StudioAdminPreviewEnvelope,
    StudioAdminPreviewResponse,
    StudioAdminPublicationEnvelope,
    StudioAdminPublicationOperationEnvelope,
    StudioAdminPublicationOperationRequest,
    StudioAdminPublicationOperationResponse,
    StudioAdminPublicationRequest,
    StudioAdminPublicationResponse,
    StudioAdminSourceItemRequest,
    StudioAdminSourcePackRequest,
    StudioAdminSourcePackValidateRequest,
    StudioAdminWeeklyPackCreateRequest,
    StudioAdminWeeklyPackEnvelope,
    StudioAdminWeeklyPackGenerateRequest,
    StudioAdminWeeklyPackListEnvelope,
    StudioAdminWeeklyPackResponse,
)
from app.application.ports.idempotency import IdempotencyStorePort

router = APIRouter(prefix="/api/admin/v1", tags=["studio-admin"])


def _correlation_id(request: Request, x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID")) -> str:
    existing = getattr(request.state, "correlation_id", "")
    if existing:
        return existing
    value = x_correlation_id or str(uuid4())
    request.state.correlation_id = value
    return value


def _filters(
    status_value: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    asset_type: str | None = Query(default=None, alias="asset_type"),
    campaign_filter: str | None = Query(default=None, alias="campaign"),
    asset_filter: str | None = Query(default=None, alias="asset"),
    actor_filter: str | None = Query(default=None, alias="actor"),
    event_filter: str | None = Query(default=None, alias="event"),
    result_filter: str | None = Query(default=None, alias="result"),
    period_from: datetime | None = Query(default=None),
    period_to: datetime | None = Query(default=None),
    published: bool | None = Query(default=None),
    in_error: bool | None = Query(default=None),
    pending_validation: bool | None = Query(default=None),
) -> dict[str, object]:
    return {
        "status": status_value,
        "channel": channel,
        "asset_type": asset_type,
        "campaign_id": campaign_filter,
        "asset_id": asset_filter,
        "actor_id": actor_filter,
        "event": event_filter,
        "result": result_filter,
        "period_from": period_from,
        "period_to": period_to,
        "published": published,
        "in_error": in_error,
        "pending_validation": pending_validation,
    }


def _pagination(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict[str, object]:
    return {
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }


def _to_http_error(exc: Exception, correlation_id: str) -> HTTPException:
    if isinstance(exc, (CampaignNotFoundError, WeeklyCommunicationPackNotFoundError, EditorialSourcePackNotFoundError, EditorialSourceItemNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"correlation_id": correlation_id, "detail": str(exc)})
    if isinstance(exc, DomainError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"correlation_id": correlation_id, "detail": str(exc)})
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"correlation_id": correlation_id, "detail": str(exc)})


def _normalize(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _etag_payload(payload: dict) -> str:
    return sha256_hexdigest(json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":")))


def _apply_cache(request: Request, response: Response, payload: dict, if_none_match: str | None) -> Response | None:
    cacheable_payload = dict(payload)
    cacheable_payload.pop("correlation_id", None)
    etag = _etag_payload(cacheable_payload)
    response.headers["ETag"] = etag
    if if_none_match and if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return None


def _campaign_response(item) -> StudioAdminCampaignResponse:
    payload = _normalize(item)
    if payload.get("last_event") is not None:
        payload["last_event"] = payload["last_event"]
    return StudioAdminCampaignResponse(**payload)


def _asset_response(item) -> StudioAdminAssetResponse:
    payload = _normalize(item)
    payload["approval"] = payload["approval"]
    return StudioAdminAssetResponse(**payload)


def _bulk_decision_response(item) -> StudioAdminBulkDecisionResponse:
    payload = _normalize(item)
    payload["assets"] = [_asset_response(asset).model_dump(mode="json") for asset in item.assets]
    return StudioAdminBulkDecisionResponse(**payload)


def _publication_operation_response(item) -> StudioAdminPublicationOperationResponse:
    return StudioAdminPublicationOperationResponse(**_normalize(item))


def _weekly_pack_response(item) -> StudioAdminWeeklyPackResponse:
    return StudioAdminWeeklyPackResponse(**_normalize(item))


def _editorial_source_pack_response(item) -> StudioAdminEditorialSourcePackResponse:
    return StudioAdminEditorialSourcePackResponse(**_normalize(item))


def _editorial_source_preview_response(item) -> StudioAdminEditorialSourcePreviewResponse:
    return StudioAdminEditorialSourcePreviewResponse(**_normalize(item))


@router.get("/dashboard", response_model=StudioAdminDashboardEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_dashboard(
    request: Request,
    response: Response,
    filters: dict[str, object] = Depends(_filters),
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    data = StudioAdminDashboardResponse(**_normalize(service.dashboard(filters)))
    envelope = StudioAdminDashboardEnvelope(correlation_id=correlation_id, data=data)
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/campaigns", response_model=StudioAdminCampaignListEnvelope, responses={304: {"description": "Not Modified"}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_campaigns(
    request: Request,
    response: Response,
    filters: dict[str, object] = Depends(_filters),
    pagination: dict[str, object] = Depends(_pagination),
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    items, total = service.list_campaigns(filters, **pagination)
    envelope = StudioAdminCampaignListEnvelope(
        correlation_id=correlation_id,
        data=[_campaign_response(item) for item in items],
        pagination=StudioAdminPaginationResponse(page=pagination["page"], page_size=pagination["page_size"], total=total),
    )
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/campaigns/{campaignId}", response_model=StudioAdminCampaignEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_campaign(
    request: Request,
    response: Response,
    campaignId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminCampaignEnvelope(correlation_id=correlation_id, data=_campaign_response(service.get_campaign(campaignId)))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.post("/weekly-packs", response_model=StudioAdminWeeklyPackEnvelope)
def create_weekly_pack(
    payload: StudioAdminWeeklyPackCreateRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminWeeklyPackEnvelope(
            correlation_id=correlation_id,
            data=_weekly_pack_response(
                service.create_weekly_pack(
                    week_reference=payload.week_reference,
                    year=payload.year,
                    week_number=payload.week_number,
                    pilot_mode=payload.pilot_mode,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                )
            ),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/weekly-packs", response_model=StudioAdminWeeklyPackListEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_weekly_packs(
    request: Request,
    response: Response,
    pagination: dict[str, object] = Depends(_pagination),
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    items, total = service.list_weekly_packs(**pagination)
    envelope = StudioAdminWeeklyPackListEnvelope(
        correlation_id=correlation_id,
        data=[_weekly_pack_response(item) for item in items],
        pagination=StudioAdminPaginationResponse(page=pagination["page"], page_size=pagination["page_size"], total=total),
    )
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/weekly-packs/{id}", response_model=StudioAdminWeeklyPackEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_weekly_pack(
    request: Request,
    response: Response,
    id: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminWeeklyPackEnvelope(correlation_id=correlation_id, data=_weekly_pack_response(service.get_weekly_pack(id)))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.post("/weekly-packs/{id}/generate", response_model=StudioAdminWeeklyPackEnvelope)
def generate_weekly_pack(
    id: str,
    payload: StudioAdminWeeklyPackGenerateRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminWeeklyPackEnvelope(
            correlation_id=correlation_id,
            data=_weekly_pack_response(service.generate_weekly_pack(id, actor=principal.actor_id, correlation_id=correlation_id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/weekly-packs/{id}/close", response_model=StudioAdminWeeklyPackEnvelope)
def close_weekly_pack(
    id: str,
    payload: StudioAdminWeeklyPackGenerateRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminWeeklyPackEnvelope(
            correlation_id=correlation_id,
            data=_weekly_pack_response(service.close_weekly_pack(id, actor=principal.actor_id, correlation_id=correlation_id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/source-packs", response_model=StudioAdminEditorialSourcePackEnvelope)
def create_source_pack(
    payload: StudioAdminSourcePackRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(
                service.create_editorial_source_pack(
                    weekly_pack_id=payload.weekly_pack_id,
                    campaign_type=payload.campaign_type,
                    title=payload.title,
                    summary=payload.summary,
                    confidentiality_level=payload.confidentiality_level,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                )
            ),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/source-packs/{id}", response_model=StudioAdminEditorialSourcePackEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_source_pack(
    id: str,
    correlation_id: str = Depends(_correlation_id),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(service.get_editorial_source_pack(id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.put("/source-packs/{id}", response_model=StudioAdminEditorialSourcePackEnvelope)
def update_source_pack(
    id: str,
    payload: StudioAdminSourcePackRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(
                service.update_editorial_source_pack(
                    id,
                    title=payload.title,
                    summary=payload.summary,
                    confidentiality_level=payload.confidentiality_level,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                )
            ),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/source-packs/{id}/validate", response_model=StudioAdminEditorialSourcePackEnvelope)
def validate_source_pack(
    id: str,
    payload: StudioAdminSourcePackValidateRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(service.validate_editorial_source_pack(id, actor=principal.actor_id, correlation_id=correlation_id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/source-packs/{id}/items", response_model=StudioAdminEditorialSourcePackEnvelope)
def add_source_pack_item(
    id: str,
    payload: StudioAdminSourceItemRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(
                service.add_editorial_source_item(id, payload=payload.model_dump(), actor=principal.actor_id, correlation_id=correlation_id)
            ),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.put("/source-packs/{id}/items/{itemId}", response_model=StudioAdminEditorialSourcePackEnvelope)
def update_source_pack_item(
    id: str,
    itemId: str,
    payload: StudioAdminSourceItemRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(
                service.update_editorial_source_item(id, itemId, payload=payload.model_dump(), actor=principal.actor_id, correlation_id=correlation_id)
            ),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.delete("/source-packs/{id}/items/{itemId}", response_model=StudioAdminEditorialSourcePackEnvelope)
def delete_source_pack_item(
    id: str,
    itemId: str,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePackEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_pack_response(service.delete_editorial_source_item(id, itemId, actor=principal.actor_id, correlation_id=correlation_id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/source-packs/{id}/editorial-preview", response_model=StudioAdminEditorialSourcePreviewEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def preview_source_pack_editorial_facts(
    id: str,
    correlation_id: str = Depends(_correlation_id),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        return StudioAdminEditorialSourcePreviewEnvelope(
            correlation_id=correlation_id,
            data=_editorial_source_preview_response(service.preview_editorial_source_pack(id)),
        )
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/campaigns/{campaignId}/assets", response_model=StudioAdminAssetListEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_campaign_assets(
    request: Request,
    response: Response,
    campaignId: str,
    filters: dict[str, object] = Depends(_filters),
    pagination: dict[str, object] = Depends(_pagination),
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        items, total = service.list_campaign_assets(campaignId, filters, **pagination)
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    envelope = StudioAdminAssetListEnvelope(
        correlation_id=correlation_id,
        data=[_asset_response(item) for item in items],
        pagination=StudioAdminPaginationResponse(page=pagination["page"], page_size=pagination["page_size"], total=total),
    )
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/assets/{assetId}", response_model=StudioAdminAssetEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset(
    request: Request,
    response: Response,
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminAssetEnvelope(correlation_id=correlation_id, data=_asset_response(service.get_asset(assetId)))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/assets/{assetId}/versions", response_model=StudioAdminAssetVersionListEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset_versions(
    request: Request,
    response: Response,
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        data = [StudioAdminAssetVersionResponse(**_normalize(item)) for item in service.get_asset_versions(assetId)]
        envelope = StudioAdminAssetVersionListEnvelope(correlation_id=correlation_id, data=data)
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/assets/{assetId}/evidence", response_model=StudioAdminEvidenceListEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset_evidence(
    request: Request,
    response: Response,
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        data = [StudioAdminEvidenceResponse(**_normalize(item)) for item in service.get_asset_evidence(assetId)]
        envelope = StudioAdminEvidenceListEnvelope(correlation_id=correlation_id, data=data)
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/assets/{assetId}/preview", response_model=StudioAdminPreviewEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset_preview(
    request: Request,
    response: Response,
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminPreviewEnvelope(correlation_id=correlation_id, data=StudioAdminPreviewResponse(**_normalize(service.get_asset_preview(assetId))))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/assets/{assetId}/publication", response_model=StudioAdminPublicationEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset_publication(
    request: Request,
    response: Response,
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminPublicationEnvelope(correlation_id=correlation_id, data=StudioAdminPublicationResponse(**_normalize(service.get_asset_publication(assetId))))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.put("/assets/{assetId}/draft", response_model=StudioAdminAssetEnvelope)
def update_asset_draft(
    request: Request,
    assetId: str,
    payload: StudioAdminAssetDraftUpdateRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminAssetEnvelope(
            correlation_id=correlation_id,
            data=_asset_response(
                service.update_asset_draft(
                    assetId,
                    actor=principal.actor_id,
                    expected_version=payload.expected_version,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                    title=payload.title,
                    subject=payload.subject,
                    content_html=payload.content_html,
                    content_text=payload.content_text,
                    excerpt=payload.excerpt,
                    call_to_action=payload.call_to_action,
                    target_url=payload.target_url,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/request-regeneration", response_model=StudioAdminAssetEnvelope)
def request_asset_regeneration(
    request: Request,
    assetId: str,
    payload: StudioAdminAssetDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminAssetEnvelope(
            correlation_id=correlation_id,
            data=_asset_response(
                service.request_asset_regeneration(
                    assetId,
                    actor=principal.actor_id,
                    expected_version=payload.expected_version,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/request-changes", response_model=StudioAdminAssetEnvelope)
def request_asset_changes(
    request: Request,
    assetId: str,
    payload: StudioAdminAssetCommentDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminAssetEnvelope(
            correlation_id=correlation_id,
            data=_asset_response(
                service.request_asset_changes(
                    assetId,
                    actor=principal.actor_id,
                    expected_version=payload.expected_version,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/approve", response_model=StudioAdminAssetEnvelope)
def approve_asset(
    request: Request,
    assetId: str,
    payload: StudioAdminAssetDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminAssetEnvelope(
            correlation_id=correlation_id,
            data=_asset_response(
                service.approve_asset(
                    assetId,
                    actor=principal.actor_id,
                    expected_version=payload.expected_version,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/reject", response_model=StudioAdminAssetEnvelope)
def reject_asset(
    request: Request,
    assetId: str,
    payload: StudioAdminAssetCommentDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminAssetEnvelope(
            correlation_id=correlation_id,
            data=_asset_response(
                service.reject_asset(
                    assetId,
                    actor=principal.actor_id,
                    expected_version=payload.expected_version,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/campaigns/{campaignId}/approve-ready-assets", response_model=StudioAdminBulkDecisionEnvelope)
def approve_ready_assets(
    request: Request,
    campaignId: str,
    payload: StudioAdminBulkDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"campaign_id": campaignId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminBulkDecisionEnvelope(
            correlation_id=correlation_id,
            data=_bulk_decision_response(
                service.approve_ready_assets(
                    campaignId,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/campaigns/{campaignId}/reject-ready-assets", response_model=StudioAdminBulkDecisionEnvelope)
def reject_ready_assets(
    request: Request,
    campaignId: str,
    payload: StudioAdminBulkCommentDecisionRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"campaign_id": campaignId, **payload.model_dump()}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminBulkDecisionEnvelope(
            correlation_id=correlation_id,
            data=_bulk_decision_response(
                service.reject_ready_assets(
                    campaignId,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    comment=payload.comment,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/assets/{assetId}/publication-readiness", response_model=StudioAdminPublicationOperationEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_REVIEW))])
def get_asset_publication_readiness(
    assetId: str,
    scheduled_at: datetime | None = None,
    correlation_id: str = Depends(_correlation_id),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(
                service.get_asset_publication_readiness(assetId, correlation_id=correlation_id, scheduled_at=scheduled_at)
            ),
        )
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/create-preview", response_model=StudioAdminPublicationOperationEnvelope)
def create_asset_publication_preview(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationOperationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(service.create_asset_preview(assetId, actor=principal.actor_id, correlation_id=correlation_id)),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/schedule", response_model=StudioAdminPublicationOperationEnvelope)
def schedule_asset_publication(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationOperationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    if payload.scheduled_at is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"correlation_id": correlation_id, "detail": "scheduled_at is required."})
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(
                service.schedule_asset_publication(
                    assetId,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                    scheduled_at=payload.scheduled_at,
                    idempotency_key=idempotency_key,
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/publish", response_model=StudioAdminPublicationOperationEnvelope)
def publish_asset(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    replay_key = idempotency_key or payload.idempotency_key
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, replay_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(
                service.publish_asset_operation(
                    assetId,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                    idempotency_key=payload.idempotency_key,
                )
            ),
        )
        store_idempotent_response(request, replay_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/cancel-publication", response_model=StudioAdminPublicationOperationEnvelope)
def cancel_asset_publication(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationOperationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(service.cancel_asset_publication(assetId, actor=principal.actor_id, correlation_id=correlation_id)),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/retry-publication", response_model=StudioAdminPublicationOperationEnvelope)
def retry_asset_publication(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    replay_key = idempotency_key or payload.idempotency_key
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, replay_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(
                service.retry_asset_publication(
                    assetId,
                    actor=principal.actor_id,
                    correlation_id=correlation_id,
                    idempotency_key=payload.idempotency_key,
                )
            ),
        )
        store_idempotent_response(request, replay_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/assets/{assetId}/unpublish", response_model=StudioAdminPublicationOperationEnvelope)
def unpublish_asset(
    request: Request,
    assetId: str,
    payload: StudioAdminPublicationOperationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"asset_id": assetId, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(service.unpublish_asset_operation(assetId, actor=principal.actor_id, correlation_id=correlation_id)),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/assets/{assetId}/publication-status", response_model=StudioAdminPublicationOperationEnvelope, dependencies=[Depends(require_studio_admin_permission(GROWTH_PUBLISH))])
def get_asset_publication_status(
    assetId: str,
    correlation_id: str = Depends(_correlation_id),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminPublicationOperationEnvelope(
            correlation_id=correlation_id,
            data=_publication_operation_response(service.get_asset_publication_operation_status(assetId, correlation_id=correlation_id)),
        )
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/channels", response_model=StudioAdminChannelListEnvelope, responses={304: {"description": "Not Modified"}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_channels(
    request: Request,
    response: Response,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    envelope = StudioAdminChannelListEnvelope(
        correlation_id=correlation_id,
        data=[StudioAdminChannelResponse(**_normalize(item)) for item in service.list_channels()],
    )
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/channels/{channel}", response_model=StudioAdminChannelEnvelope, responses={304: {"description": "Not Modified"}, 404: {"model": StudioAdminErrorResponse}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_channel(
    request: Request,
    response: Response,
    channel: str,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    try:
        envelope = StudioAdminChannelEnvelope(correlation_id=correlation_id, data=StudioAdminChannelResponse(**_normalize(service.get_channel(channel))))
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.post("/channels/{channel}/health-check", response_model=StudioAdminChannelEnvelope)
def health_check_channel(
    request: Request,
    channel: str,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"channel": channel, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminChannelEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminChannelResponse(
                **_normalize(
                    service.health_check_channel(
                        channel,
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/channels/{channel}/enable", response_model=StudioAdminChannelEnvelope)
def enable_channel(
    request: Request,
    channel: str,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"channel": channel, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminChannelEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminChannelResponse(
                **_normalize(
                    service.enable_channel(
                        channel,
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                        confirmation=payload.confirmation,
                        expires_in_minutes=payload.expires_in_minutes,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/channels/{channel}/disable", response_model=StudioAdminChannelEnvelope)
def disable_channel(
    request: Request,
    channel: str,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"channel": channel, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminChannelEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminChannelResponse(
                **_normalize(
                    service.disable_channel(
                        channel,
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/channels/{channel}/activate-kill-switch", response_model=StudioAdminChannelEnvelope)
def activate_channel_kill_switch(
    request: Request,
    channel: str,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"channel": channel, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminChannelEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminChannelResponse(
                **_normalize(
                    service.activate_channel_kill_switch(
                        channel,
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/channels/{channel}/deactivate-kill-switch", response_model=StudioAdminChannelEnvelope)
def deactivate_channel_kill_switch(
    request: Request,
    channel: str,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = {"channel": channel, **payload.model_dump(mode="json")}
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminChannelEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminChannelResponse(
                **_normalize(
                    service.deactivate_channel_kill_switch(
                        channel,
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                        confirmation=payload.confirmation,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/global-kill-switch/activate", response_model=StudioAdminGlobalKillSwitchEnvelope)
def activate_global_kill_switch(
    request: Request,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminGlobalKillSwitchEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminGlobalKillSwitchResponse(
                **_normalize(
                    service.activate_global_kill_switch(
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.post("/global-kill-switch/deactivate", response_model=StudioAdminGlobalKillSwitchEnvelope)
def deactivate_global_kill_switch(
    request: Request,
    payload: StudioAdminChannelMutationRequest,
    correlation_id: str = Depends(_correlation_id),
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_CONFIGURE)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: IdempotencyStorePort = Depends(get_idempotency_store),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    body = payload.model_dump(mode="json")
    cached = resolve_idempotent_response(request, idempotency_key, body, store)
    if cached is not None:
        return cached
    try:
        envelope = StudioAdminGlobalKillSwitchEnvelope(
            correlation_id=correlation_id,
            data=StudioAdminGlobalKillSwitchResponse(
                **_normalize(
                    service.deactivate_global_kill_switch(
                        actor=principal.actor_id,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                        confirmation=payload.confirmation,
                    )
                )
            ),
        )
        store_idempotent_response(request, idempotency_key, body, 200, jsonable_encoder(envelope), store)
        return envelope
    except Exception as exc:
        raise _to_http_error(exc, correlation_id) from exc


@router.get("/audit-events", response_model=StudioAdminAuditEventListEnvelope, responses={304: {"description": "Not Modified"}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_AUDIT))])
def list_audit_events(
    request: Request,
    response: Response,
    filters: dict[str, object] = Depends(_filters),
    pagination: dict[str, object] = Depends(_pagination),
    event_type: str | None = Query(default=None, alias="event_type"),
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    filters["event_type"] = event_type
    items, total = service.list_audit_events(filters, page=pagination["page"], page_size=pagination["page_size"])
    envelope = StudioAdminAuditEventListEnvelope(
        correlation_id=correlation_id,
        data=[StudioAdminAuditEventResponse(**_normalize(item)) for item in items],
        pagination=StudioAdminPaginationResponse(page=pagination["page"], page_size=pagination["page_size"], total=total),
    )
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope


@router.get("/audit-events/export.csv", dependencies=[Depends(require_studio_admin_permission(GROWTH_AUDIT))])
def export_audit_events_csv(
    filters: dict[str, object] = Depends(_filters),
    event_type: str | None = Query(default=None, alias="event_type"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    filters["event_type"] = event_type
    content = service.export_audit_events_csv(filters)
    return Response(content=content, media_type="text/csv")


@router.get("/health", response_model=StudioAdminHealthEnvelope, responses={304: {"description": "Not Modified"}}, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_health(
    request: Request,
    response: Response,
    correlation_id: str = Depends(_correlation_id),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    service: StudioAdminService = Depends(get_studio_admin_service),
):
    envelope = StudioAdminHealthEnvelope(correlation_id=correlation_id, data=StudioAdminHealthResponse(**_normalize(service.health())))
    cached = _apply_cache(request, response, envelope.model_dump(mode="json"), if_none_match)
    return cached or envelope
