from __future__ import annotations

import html
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.core.security import verify_review_admin
from app.domain.errors import CampaignNotFoundError, EditorialGenerationBlockedError
from app.entrypoints.api.dependencies import get_review_portal_service

router = APIRouter(tags=["review-portal"])


def _render_review_page(
    review,
    actor: str,
    token: str,
    *,
    error: str = "",
    banner: str = "",
    actions_enabled: bool = True,
    studio_url: str = "",
) -> HTMLResponse:
    quality = html.escape(str(review.quality_control))
    exclusions = html.escape(str(review.exclusions))
    evidence_items = "".join(f"<li>{html.escape(item)}</li>" for item in review.evidence_ids)
    alert = f"<p style='color:#a00'>{html.escape(error)}</p>" if error else ""
    banner_html = f"<div style='padding:1rem;border:1px solid #d9a441;background:#fff8e1;margin-bottom:1rem'><strong>{html.escape(banner)}</strong></div>" if banner else ""
    approved = "yes" if review.approved_at else "no"
    action_note = "" if actions_enabled else f"<p><strong>Administration moved to Studio.</strong> Continue in <a href='{html.escape(studio_url)}'>MAPSI Studio</a>.</p>"
    disabled = "disabled" if not actions_enabled else ""
    body = f"""
    <html><body style="font-family: sans-serif; max-width: 900px; margin: 2rem auto;">
      <h1>Review Portal</h1>
      <p><strong>Reviewer:</strong> {html.escape(actor)}</p>
      {banner_html}
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
      {action_note}
      <h3>Modifier le contenu</h3>
      <form method="post" action="/review/{token}/edit">
        <label>Subject</label><br /><input name="email_subject" value="{html.escape(review.email_subject)}" style="width:100%" {disabled}/><br />
        <label>Preheader</label><br /><input name="email_preheader" value="{html.escape(review.email_preheader)}" style="width:100%" {disabled}/><br />
        <label>HTML</label><br /><textarea name="email_html" rows="8" style="width:100%" {disabled}>{html.escape(review.email_html)}</textarea><br />
        <label>Text</label><br /><textarea name="email_text" rows="8" style="width:100%" {disabled}>{html.escape(review.email_text)}</textarea><br />
        <button type="submit" {disabled}>Enregistrer</button>
      </form>
      <h3>Actions</h3>
      <form method="post" action="/review/{token}/request-changes"><input name="comment" placeholder="Commentaire" {disabled}/><button type="submit" {disabled}>Nouvelle version</button></form>
      <form method="post" action="/review/{token}/approve"><button type="submit" {disabled}>Approuver</button></form>
      <form method="post" action="/review/{token}/reject"><input name="comment" placeholder="Commentaire" {disabled}/><button type="submit" {disabled}>Rejeter</button></form>
      <form method="post" action="/review/{token}/revoke"><button type="submit" {disabled}>Revoquer le jeton</button></form>
    </body></html>
    """
    return HTMLResponse(body)


def _render_moved_page(*, mode: str, studio_url: str, emergency: bool = False) -> HTMLResponse:
    title = "Review Portal Disabled" if mode == "disabled" else "Administration Moved"
    message = "L'administration Growth a ete deplacee dans MAPSI Studio."
    if emergency:
        message = "Le portail transitoire est reserve aux operations d'urgence. Utiliser MAPSI Studio en priorite."
    return HTMLResponse(
        f"""
        <html><body style="font-family:sans-serif;max-width:800px;margin:3rem auto">
          <h1>{html.escape(title)}</h1>
          <p>{html.escape(message)}</p>
          <p><a href="{html.escape(studio_url)}">Ouvrir MAPSI Studio</a></p>
        </body></html>
        """,
        status_code=status.HTTP_200_OK,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, CampaignNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EditorialGenerationBlockedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _read_form(request: Request) -> dict[str, str]:
    payload = (await request.body()).decode("utf-8")
    parsed = parse_qs(payload, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _review_source_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else ""


def _settings_mode() -> str:
    return get_settings().review_portal_mode.strip().lower()


def _enforce_emergency_access(
    *,
    actor: str,
    request: Request,
    token: str,
    service: ReviewPortalService,
    x_review_emergency_key: str | None,
) -> None:
    settings = get_settings()
    allowlist = {item.strip() for item in settings.review_portal_emergency_allowlist.split(",") if item.strip()}
    review = service.get_review_by_token(token)
    source_ip = _review_source_ip(request)
    if actor not in allowlist or not x_review_emergency_key or not secrets.compare_digest(x_review_emergency_key, settings.review_portal_emergency_key):
        service.audit_log.append(
            review.campaign_run_id,
            "review.portal_emergency_access_denied",
            {"mode": "emergency-only"},
            actor_id=actor,
            actor_source="review_portal",
            source_ip=source_ip,
            result="DENIED",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Emergency access only.")
    service.audit_log.append(
        review.campaign_run_id,
        "review.portal_emergency_access_granted",
        {"mode": "emergency-only"},
        actor_id=actor,
        actor_source="review_portal",
        source_ip=source_ip,
        result="SUCCESS",
    )


def _readonly_redirect() -> RedirectResponse:
    return RedirectResponse(url=get_settings().review_portal_studio_url, status_code=status.HTTP_303_SEE_OTHER)


def _audit_portal_notice(service: ReviewPortalService, token: str, *, actor: str, event_type: str, result: str, request: Request) -> None:
    review = service.get_review_by_token(token)
    service.audit_log.append(
        review.campaign_run_id,
        event_type,
        {"mode": _settings_mode()},
        actor_id=actor,
        actor_source="review_portal",
        source_ip=_review_source_ip(request),
        result=result,
    )


@router.get("/review/{token}", response_class=HTMLResponse)
def view_review(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> HTMLResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_notice_shown", result="SUCCESS", request=request)
            return _render_moved_page(mode=mode, studio_url=settings.review_portal_studio_url)
        review = service.get_review_by_token(token)
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
            return _render_review_page(
                review,
                actor,
                token,
                banner=settings.review_portal_emergency_banner,
                studio_url=settings.review_portal_studio_url,
            )
        if mode == "readonly":
            service.audit_log.append(
                review.campaign_run_id,
                "review.portal_readonly_viewed",
                {"mode": mode},
                actor_id=actor,
                actor_source="review_portal",
                source_ip=_review_source_ip(request),
                result="SUCCESS",
            )
            return _render_review_page(
                review,
                actor,
                token,
                banner="Lecture seule. Les decisions ont ete deplacees dans MAPSI Studio.",
                actions_enabled=False,
                studio_url=settings.review_portal_studio_url,
            )
        service.audit_log.append(
            review.campaign_run_id,
            "review.portal_viewed",
            {"mode": mode},
            actor_id=actor,
            actor_source="review_portal",
            source_ip=_review_source_ip(request),
            result="SUCCESS",
        )
        return _render_review_page(review, actor, token, studio_url=settings.review_portal_studio_url)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/edit", response_class=HTMLResponse)
async def edit_review(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> HTMLResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_write_blocked", result="DENIED", request=request)
            return _render_moved_page(mode=mode, studio_url=settings.review_portal_studio_url)
        if mode == "readonly":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_readonly_write_blocked", result="DENIED", request=request)
            return _readonly_redirect()
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
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
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> HTMLResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_write_blocked", result="DENIED", request=request)
            return _render_moved_page(mode=mode, studio_url=settings.review_portal_studio_url)
        if mode == "readonly":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_readonly_write_blocked", result="DENIED", request=request)
            return _readonly_redirect()
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
        form = await _read_form(request)
        review = service.request_new_version(token, actor=actor, comment=form.get("comment", ""))
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/approve", response_class=HTMLResponse)
def approve_review(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> HTMLResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_write_blocked", result="DENIED", request=request)
            return _render_moved_page(mode=mode, studio_url=settings.review_portal_studio_url)
        if mode == "readonly":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_readonly_write_blocked", result="DENIED", request=request)
            return _readonly_redirect()
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
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
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> HTMLResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_write_blocked", result="DENIED", request=request)
            return _render_moved_page(mode=mode, studio_url=settings.review_portal_studio_url)
        if mode == "readonly":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_readonly_write_blocked", result="DENIED", request=request)
            return _readonly_redirect()
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
        form = await _read_form(request)
        review = service.reject(token, actor=actor, comment=form.get("comment", ""))
        return _render_review_page(review, actor, token)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/review/{token}/revoke")
def revoke_review_token(
    request: Request,
    token: str,
    actor: str = Depends(verify_review_admin),
    service: ReviewPortalService = Depends(get_review_portal_service),
    x_review_emergency_key: str | None = Header(default=None, alias="X-Review-Emergency-Key"),
) -> RedirectResponse:
    try:
        settings = get_settings()
        mode = _settings_mode()
        if mode == "disabled":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_disabled_write_blocked", result="DENIED", request=request)
            return RedirectResponse(url=settings.review_portal_studio_url, status_code=status.HTTP_303_SEE_OTHER)
        if mode == "readonly":
            _audit_portal_notice(service, token, actor=actor, event_type="review.portal_readonly_write_blocked", result="DENIED", request=request)
            return _readonly_redirect()
        if mode == "emergency-only":
            _enforce_emergency_access(actor=actor, request=request, token=token, service=service, x_review_emergency_key=x_review_emergency_key)
        service.revoke_token(token, actor=actor)
        return RedirectResponse(url="/campaigns", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        raise _map_error(exc) from exc
