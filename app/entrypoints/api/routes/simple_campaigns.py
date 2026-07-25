from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.simple_campaign_service import (
    CreateSimpleCampaignCommand,
    PublishSimpleCampaignCommand,
    SimpleCampaignService,
    UpdateSimpleAssetCommand,
)
from app.core.security import GROWTH_PUBLISH, GROWTH_REVIEW, GROWTH_VIEW, require_studio_admin_permission
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, DomainError, InvalidStateTransitionError
from app.entrypoints.api.dependencies import get_simple_campaign_service
from app.entrypoints.api.simple_campaign_schemas import (
    OlingThemeCatalogResponse,
    SimpleAssetResponse,
    SimpleAssetUpdateRequest,
    SimpleCampaignCreateRequest,
    SimpleCampaignPublishRequest,
    SimpleCampaignResponse,
    SimplePublicationResponse,
)

router = APIRouter(prefix="/studio-simple", tags=["studio-simple"])


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (CampaignPublicationForbiddenError, InvalidStateTransitionError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _response(service: SimpleCampaignService, campaign) -> SimpleCampaignResponse:
    return SimpleCampaignResponse(
        id=campaign.id,
        name=campaign.name,
        campaign_type=campaign.campaign_type,
        theme=campaign.theme,
        status=service.simple_status(campaign),
        selected_channels=list(campaign.selected_channels or []),
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        content_assets=[
            SimpleAssetResponse(
                id=item.id,
                channel=service.external_channel(item.channel),
                asset_type=item.asset_type,
                title=item.title,
                content_html=item.content_html,
                content_text=item.content_text,
                excerpt=item.excerpt,
                call_to_action=item.call_to_action,
                illustration_suggestion=str((item.results or {}).get("illustration_suggestion", "")),
                status=service.simple_asset_status(item),
                version=item.content_version,
                public_url=item.external_publication_url,
                published_at=item.published_at,
            )
            for item in campaign.content_assets
        ],
        publications=[
            SimplePublicationResponse(
                id=item.id,
                channel=service.external_channel(item.channel),
                external_reference=item.external_reference,
                external_url=item.external_url,
                published_at=item.published_at,
            )
            for item in campaign.publications
        ],
    )


@router.get("/oling-themes", response_model=OlingThemeCatalogResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_oling_themes(service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> OlingThemeCatalogResponse:
    return OlingThemeCatalogResponse(items=service.list_oling_themes())


@router.post("/campaigns", response_model=SimpleCampaignResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_studio_admin_permission(GROWTH_REVIEW))])
def create_campaign(
    payload: SimpleCampaignCreateRequest,
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        campaign = service.create_campaign(
            CreateSimpleCampaignCommand(
                name=payload.name,
                campaign_type=payload.campaign_type,
                theme=payload.theme,
                selected_channels=payload.selected_channels,
            )
        )
        return _response(service, campaign)
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.get("/campaigns", response_model=list[SimpleCampaignResponse], dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_campaigns(service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> list[SimpleCampaignResponse]:
    return [_response(service, campaign) for campaign in service.list_campaigns()]


@router.get("/campaigns/{campaign_id}", response_model=SimpleCampaignResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_campaign(campaign_id: str, service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> SimpleCampaignResponse:
    try:
        return _response(service, service.get_campaign(campaign_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/generate", response_model=SimpleCampaignResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_REVIEW))])
def generate_campaign(campaign_id: str, service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> SimpleCampaignResponse:
    try:
        return _response(service, service.generate_campaign(campaign_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.put("/campaigns/{campaign_id}/assets/{asset_id}", response_model=SimpleCampaignResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_REVIEW))])
def update_asset(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetUpdateRequest,
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(
            service,
            service.update_asset(
                campaign_id,
                asset_id,
                UpdateSimpleAssetCommand(
                    title=payload.title,
                    content_html=payload.content_html,
                    content_text=payload.content_text,
                    expected_version=payload.expected_version,
                ),
            ),
        )
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/publish", response_model=SimpleCampaignResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_PUBLISH))])
def publish_campaign(
    campaign_id: str,
    payload: SimpleCampaignPublishRequest,
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.publish_campaign(campaign_id, PublishSimpleCampaignCommand(channels=payload.channels)))
    except DomainError as exc:
        raise _to_http_error(exc) from exc
