from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.application.services.simple_campaign_service import (
    ApproveSimpleAssetCommand,
    CreateSimpleCampaignCommand,
    GenerateSimpleImageCommand,
    PublishSimpleCampaignCommand,
    ReviewSimpleAssetCommand,
    SimpleCampaignService,
    UpdateSimpleAssetCommand,
)
from app.core.security import GROWTH_APPROVE, GROWTH_PUBLISH, GROWTH_REVIEW, GROWTH_VIEW, StudioAdminPrincipal, require_studio_admin_permission
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, DomainError, InvalidStateTransitionError, OptimisticLockError
from app.entrypoints.api.dependencies import get_simple_campaign_service
from app.entrypoints.api.simple_campaign_schemas import (
    OlingThemeCatalogResponse,
    SimpleAssetDecisionRequest,
    SimpleAssetImageRequest,
    SimpleAssetSeoGeoRequest,
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
    if isinstance(exc, (CampaignPublicationForbiddenError, InvalidStateTransitionError, OptimisticLockError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _image_payload(item, service: SimpleCampaignService, *, include_data_url: bool) -> dict:
    image = dict((item.results or {}).get("image") or {})
    if image:
        image["image_url"] = f"/studio-simple/assets/{item.id}/image"
        if not include_data_url:
            image.pop("data_url", None)
    return image


def _response(service: SimpleCampaignService, campaign, *, include_image_data: bool = True) -> SimpleCampaignResponse:
    return SimpleCampaignResponse(
        id=campaign.id,
        name=campaign.name,
        campaign_type=campaign.campaign_type,
        theme=campaign.theme,
        brief=campaign.objective if campaign.objective != campaign.theme else "",
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
                image=_image_payload(item, service, include_data_url=include_image_data),
                seo_geo=dict((item.results or {}).get("seo_geo") or {}),
                status=service.simple_asset_status(item),
                version=item.content_version,
                approved_by=item.approved_by,
                approved_at=item.approved_at,
                approved_version=item.content_version if item.approved_content_hash and item.approved_content_hash == item.content_hash else None,
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
                brief=payload.brief,
                selected_channels=payload.selected_channels,
            )
        )
        return _response(service, campaign)
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.get("/campaigns", response_model=list[SimpleCampaignResponse], dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def list_campaigns(service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> list[SimpleCampaignResponse]:
    return [_response(service, campaign, include_image_data=False) for campaign in service.list_campaigns()]


@router.get("/campaigns/{campaign_id}", response_model=SimpleCampaignResponse, dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_campaign(campaign_id: str, service: SimpleCampaignService = Depends(get_simple_campaign_service)) -> SimpleCampaignResponse:
    try:
        return _response(service, service.get_campaign(campaign_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.get("/assets/{asset_id}/image", dependencies=[Depends(require_studio_admin_permission(GROWTH_VIEW))])
def get_asset_image(asset_id: str, service: SimpleCampaignService = Depends(get_simple_campaign_service)):
    try:
        path, media_type, legacy_data_url = service.get_asset_image_reference(asset_id)
    except DomainError as exc:
        raise _to_http_error(exc) from exc
    if path is not None and path.is_file():
        return FileResponse(path, media_type=media_type)
    if legacy_data_url.startswith("data:image/") and ";base64," in legacy_data_url:
        header, payload = legacy_data_url.split(",", 1)
        media_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
        import base64

        return Response(content=base64.b64decode(payload), media_type=media_type)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")


@router.post("/campaigns/{campaign_id}/generate", response_model=SimpleCampaignResponse)
def generate_campaign(
    campaign_id: str,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.generate_campaign(campaign_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.put("/campaigns/{campaign_id}/assets/{asset_id}", response_model=SimpleCampaignResponse)
def update_asset(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetUpdateRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
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


@router.post("/campaigns/{campaign_id}/assets/{asset_id}/review", response_model=SimpleCampaignResponse)
def review_asset(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetDecisionRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(
            service,
            service.review_asset(
                campaign_id,
                asset_id,
                ReviewSimpleAssetCommand(comment=payload.comment, expected_version=payload.expected_version, actor=principal.actor_id),
            ),
        )
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/assets/{asset_id}/approve", response_model=SimpleCampaignResponse)
def approve_asset(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetDecisionRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_APPROVE)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(
            service,
            service.approve_asset(
                campaign_id,
                asset_id,
                ApproveSimpleAssetCommand(comment=payload.comment, expected_version=payload.expected_version, actor=principal.actor_id),
            ),
        )
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/assets/{asset_id}/image", response_model=SimpleCampaignResponse)
def generate_asset_image(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetImageRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(
            service,
            service.generate_asset_image(
                campaign_id,
                asset_id,
                GenerateSimpleImageCommand(visual_brief=payload.visual_brief, expected_version=payload.expected_version),
            ),
        )
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/assets/{asset_id}/seo-geo", response_model=SimpleCampaignResponse)
def prepare_asset_seo_geo(
    campaign_id: str,
    asset_id: str,
    payload: SimpleAssetSeoGeoRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_REVIEW)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.prepare_asset_seo_geo(campaign_id, asset_id, expected_version=payload.expected_version))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/publish", response_model=SimpleCampaignResponse)
def publish_campaign(
    campaign_id: str,
    payload: SimpleCampaignPublishRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.publish_campaign(campaign_id, PublishSimpleCampaignCommand(channels=payload.channels)))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/unpublish", response_model=SimpleCampaignResponse)
def unpublish_campaign(
    campaign_id: str,
    payload: SimpleCampaignPublishRequest,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.unpublish_campaign(campaign_id, PublishSimpleCampaignCommand(channels=payload.channels), actor=principal.actor_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.post("/campaigns/{campaign_id}/archive", response_model=SimpleCampaignResponse)
def archive_campaign(
    campaign_id: str,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> SimpleCampaignResponse:
    try:
        return _response(service, service.archive_campaign(campaign_id, actor=principal.actor_id))
    except DomainError as exc:
        raise _to_http_error(exc) from exc


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: str,
    principal: StudioAdminPrincipal = Depends(require_studio_admin_permission(GROWTH_PUBLISH)),
    service: SimpleCampaignService = Depends(get_simple_campaign_service),
) -> None:
    try:
        service.delete_campaign(campaign_id)
    except DomainError as exc:
        raise _to_http_error(exc) from exc
