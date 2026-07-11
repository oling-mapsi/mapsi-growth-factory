import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.domain.errors import IncompatibleContractVersionError, UnauthorizedRepositoryError, WebhookSignatureInvalidError
from app.entrypoints.api.dependencies import get_github_intelligence_service

router = APIRouter(prefix="/webhooks", tags=["github-webhooks"])


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WebhookSignatureInvalidError):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(exc, UnauthorizedRepositoryError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, IncompatibleContractVersionError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    service: GitHubIntelligenceService = Depends(get_github_intelligence_service),
    x_github_delivery: str = Header(...),
    x_github_event: str = Header(...),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    payload = json.loads(body.decode("utf-8"))
    try:
        result = service.process_webhook(
            delivery_id=x_github_delivery,
            event_type=x_github_event,
            signature=x_hub_signature_256,
            body=body,
            payload=payload,
        )
        return {
            "accepted": result.accepted,
            "status": result.status,
            "product_changes_created": result.product_changes_created,
            "delivery_id": x_github_delivery,
        }
    except Exception as exc:
        raise _to_http_error(exc) from exc
