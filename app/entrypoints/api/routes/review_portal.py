from __future__ import annotations

import html
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.services.review_portal_service import ReviewPortalService
from app.core.security import verify_review_admin
from app.domain.errors import CampaignNotFoundError, EditorialGenerationBlockedError
from app.entrypoints.api.dependencies import get_review_portal_service

router = APIRouter(tags=["review-portal"])


def _render_review_page(review, actor: str, token: str, error: str = "") -> HTMLResponse:
    quality = html.escape(str(review.quality_control))
    exclusions = html.escape(str(review.exclusions))
    evidence_items = "".join(f"<li>{html.escape(item)}</li>" for item in review.evidence_ids)
    alert = f"<p style='color:#a00'>{html.escape(error)}</p>" if error else ""
    approved = "yes" if review.approved_at else "no"
    body = f"""
    <html><body style="font-family: sans-serif; max-width: 900px; margin: 2rem auto;">
      <h1>Review Portal</h1>
      <p><strong>Reviewer:</strong> {html.escape(actor)}</p>
      {alert}
      <h2>{html.escape(review.theme)}</h2>
      <p><strong>Objectif:</strong> {html.escape(review.objective)}</p>
      <p><strong>Segment:</strong> {html.escape(review.segment_label)} ({html.escape(review.segment_id)})</p>
      <p><strong>Destinataires:</strong> {review.audience_volume}</p>
      <p><strong>Exclusions:</strong> {exclusions}</p>
      <p><strong>Controle qualite:</strong> {quality}</p>
      <p><strong>Date proposee:</strong> {review.proposed_at}</p>
      <p><strong>Approved:</strong> {approved}</p>
      <h3>Preuves</h3>
      <ul>{evidence_items}</ul>
      <h3>Email HTML</h3>
      <div style="border:1px solid #ccc;padding:1rem">{review.email_html}</div>
      <h3>Email texte</h3>
      <pre style="white-space:pre-wrap;border:1px solid #ccc;padding:1rem">{html.escape(review.email_text)}</pre>
      <h3>Modifier le contenu</h3>
      <form method="post" action="/review/{token}/edit">
        <label>Subject</label><br /><input name="email_subject" value="{html.escape(review.email_subject)}" style="width:100%" /><br />
        <label>Preheader</label><br /><input name="email_preheader" value="{html.escape(review.email_preheader)}" style="width:100%" /><br />
        <label>HTML</label><br /><textarea name="email_html" rows="8" style="width:100%">{html.escape(review.email_html)}</textarea><br />
        <label>Text</label><br /><textarea name="email_text" rows="8" style="width:100%">{html.escape(review.email_text)}</textarea><br />
        <button type="submit">Enregistrer</button>
      </form>
      <h3>Actions</h3>
      <form method="post" action="/review/{token}/request-changes"><input name="comment" placeholder="Commentaire" /><button type="submit">Nouvelle version</button></form>
      <form method="post" action="/review/{token}/approve"><button type="submit">Approuver</button></form>
      <form method="post" action="/review/{token}/reject"><input name="comment" placeholder="Commentaire" /><button type="submit">Rejeter</button></form>
      <form method="post" action="/review/{token}/revoke"><button type="submit">Revoquer le jeton</button></form>
    </body></html>
    """
    return HTMLResponse(body)


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EditorialGenerationBlockedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _read_form(request: Request) -> dict[str, str]:
    payload = (await request.body()).decode("utf-8")
    parsed = parse_qs(payload, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


@router.get("/review/{token}", response_class=HTMLResponse)
def view_review(
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> HTMLResponse:
    try:
        review = service.get_review_by_token(token)
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/edit", response_class=HTMLResponse)
async def edit_review(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> HTMLResponse:
    try:
        form = await _read_form(request)
        review = service.update_content(
            token,
            actor=actor,
            email_subject=form.get("email_subject", ""),
            email_preheader=form.get("email_preheader", ""),
            email_html=form.get("email_html", ""),
            email_text=form.get("email_text", ""),
        )
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/request-changes", response_class=HTMLResponse)
async def request_changes(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> HTMLResponse:
    try:
        form = await _read_form(request)
        review = service.request_new_version(token, actor=actor, comment=form.get("comment", ""))
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/approve", response_class=HTMLResponse)
def approve_review(
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> HTMLResponse:
    try:
        review = service.approve(token, actor=actor)
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/reject", response_class=HTMLResponse)
async def reject_review(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> HTMLResponse:
    try:
        form = await _read_form(request)
        review = service.reject(token, actor=actor, comment=form.get("comment", ""))
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/revoke")
def revoke_review_token(
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
) -> RedirectResponse:
    try:
        service.revoke_token(token, actor=actor)
        return RedirectResponse(url="/campaigns", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        raise _map_error(exc) from exc
