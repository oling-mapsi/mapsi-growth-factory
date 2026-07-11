import hashlib
import json

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.application.ports.idempotency import IdempotencyStorePort


def build_request_fingerprint(payload: object) -> str:
    canonical = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_idempotent_response(
    request: Request,
    key: str | None,
    payload: object,
    store: IdempotencyStorePort,
) -> JSONResponse | None:
    if not key:
        return None
    fingerprint = build_request_fingerprint(payload)
    existing = store.get(request.method, request.url.path, key)
    if existing is None:
        return None
    if existing["request_fingerprint"] != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key already used with a different payload.",
        )
    return JSONResponse(status_code=existing["response_status"], content=existing["response_body"])


def store_idempotent_response(
    request: Request,
    key: str | None,
    payload: object,
    response_status: int,
    response_body: dict,
    store: IdempotencyStorePort,
) -> None:
    if not key:
        return
    store.save(
        method=request.method,
        path=request.url.path,
        key=key,
        request_fingerprint=build_request_fingerprint(payload),
        response_status=response_status,
        response_body=response_body,
    )
