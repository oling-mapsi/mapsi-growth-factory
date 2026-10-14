import secrets
import base64
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import ipaddress
import json
import subprocess
import tempfile
from uuid import uuid4

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings, get_studio_admin_public_keys, get_studio_admin_role_permissions
from app.core.db import get_db_session
from app.infrastructure.repositories.studio_admin_security import StudioAdminAccessAuditRepository, StudioAdminJtiRepository

basic_auth = HTTPBasic()

GROWTH_VIEW = "GROWTH_VIEW"
GROWTH_REVIEW = "GROWTH_REVIEW"
GROWTH_APPROVE = "GROWTH_APPROVE"
GROWTH_PUBLISH = "GROWTH_PUBLISH"
GROWTH_CONFIGURE = "GROWTH_CONFIGURE"
GROWTH_AUDIT = "GROWTH_AUDIT"


@dataclass
class StudioAdminPrincipal:
    actor_id: str
    roles: list[str]
    permissions: list[str]
    source: str
    issuer: str
    audience: str
    jti: str
    customer: str
    issued_at: datetime
    expires_at: datetime
    not_before: datetime | None
    key_id: str


def verify_mapsi_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().mapsi_api_key
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


def verify_review_admin(credentials: HTTPBasicCredentials = Depends(basic_auth)) -> str:
    settings = get_settings()
    if not (
        secrets.compare_digest(credentials.username, settings.review_admin_username)
        and secrets.compare_digest(credentials.password, settings.review_admin_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid review credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _bearer_token(authorization: str | None = Header(default=None, alias="Authorization")) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    return token


def _studio_admin_source_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else ""


def _enforce_studio_admin_network_allowlist(source_ip: str) -> None:
    allowed = [item.strip() for item in get_settings().studio_admin_allowed_ip_ranges.split(",") if item.strip()]
    if not allowed or not source_ip:
        return
    address = ipaddress.ip_address(source_ip)
    for candidate in allowed:
        if address in ipaddress.ip_network(candidate, strict=False):
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Source address is not allowed.")


def _studio_admin_permissions_for_roles(roles: list[str]) -> list[str]:
    mapping = get_studio_admin_role_permissions()
    permissions: set[str] = set()
    for role in roles:
        permissions.update(mapping.get(role, []))
    return sorted(permissions)


def _studio_admin_public_key_by_kid(kid: str, alg: str) -> str:
    for key in get_studio_admin_public_keys():
        if key.get("kid") == kid and key.get("alg") == alg:
            return str(key.get("public_key_pem", ""))
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown signing key.")


def _utc_from_numeric(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _verify_rs256_signature(public_key_pem: str, signing_input: bytes, signature: bytes) -> bool:
    with tempfile.NamedTemporaryFile("wb", delete=True) as message_file, tempfile.NamedTemporaryFile("wb", delete=True) as signature_file, tempfile.NamedTemporaryFile("w", delete=True) as public_key_file:
        message_file.write(signing_input)
        message_file.flush()
        signature_file.write(signature)
        signature_file.flush()
        public_key_file.write(public_key_pem)
        public_key_file.flush()
        result = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                public_key_file.name,
                "-signature",
                signature_file.name,
                message_file.name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.returncode == 0


def verify_studio_admin_token(
    request: Request,
    token: str = Depends(_bearer_token),
    session: Session = Depends(get_db_session),
) -> StudioAdminPrincipal:
    settings = get_settings()
    if not settings.studio_admin_api_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Studio admin API is disabled.")

    source_ip = _studio_admin_source_ip(request)
    _enforce_studio_admin_network_allowlist(source_ip)
    if not getattr(request.state, "correlation_id", ""):
        request.state.correlation_id = request.headers.get("X-Correlation-ID", "") or str(uuid4())

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.") from exc

    alg = str(header.get("alg") or "")
    kid = str(header.get("kid") or "")
    allowed_algorithms = [item.strip() for item in settings.studio_admin_jwt_allowed_algorithms.split(",") if item.strip()]
    if not alg or alg not in allowed_algorithms:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT algorithm is not allowed.")
    if not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT kid is required.")

    public_key = _studio_admin_public_key_by_kid(kid, alg)
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.") from exc
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = _b64url_decode(signature_segment)
    if not _verify_rs256_signature(public_key, signing_input, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT validation failed.")
    try:
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT payload is invalid.") from exc

    for claim in ("iss", "aud", "sub", "exp", "iat", "jti", "nbf"):
        if claim not in payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"JWT claim {claim} is required.")
    if str(payload.get("iss")) != settings.studio_admin_jwt_issuer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT issuer is invalid.")
    if str(payload.get("aud")) != settings.studio_admin_jwt_audience:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT audience is invalid.")

    issued_at = _utc_from_numeric(payload.get("iat"))
    expires_at = _utc_from_numeric(payload.get("exp"))
    not_before = _utc_from_numeric(payload.get("nbf"))
    if issued_at is None or expires_at is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT time claims are invalid.")
    now = datetime.now(UTC)
    leeway = settings.studio_admin_jwt_leeway_seconds
    if expires_at < now - timedelta(seconds=leeway):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT is expired.")
    if not_before is not None and not_before > now + timedelta(seconds=leeway):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT is not active yet.")
    if int(expires_at.timestamp() - issued_at.timestamp()) > settings.studio_admin_jwt_max_lifetime_seconds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT lifetime is too long.")

    roles = payload.get("roles")
    if not isinstance(roles, list) or not all(isinstance(item, str) for item in roles):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT roles are invalid.")
    permissions = _studio_admin_permissions_for_roles(list(roles))
    if not permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No Growth permissions granted.")

    actor_id = str(payload.get("sub") or "")
    jti = str(payload.get("jti") or "")
    customer = str(payload.get("customer") or "")
    if not actor_id or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT subject or jti is missing.")

    jti_repository = StudioAdminJtiRepository(session)
    if settings.studio_admin_enforce_replay_protection and jti_repository.exists(jti):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="JWT replay detected.")
    if settings.studio_admin_enforce_replay_protection:
        try:
            jti_repository.register(
                jti=jti,
                issuer=str(payload["iss"]),
                audience=str(payload["aud"]),
                subject=actor_id,
                expires_at=expires_at,
                key_id=kid,
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="JWT replay detected.") from exc

    principal = StudioAdminPrincipal(
        actor_id=actor_id,
        roles=list(roles),
        permissions=permissions,
        source="mapsi-studio",
        issuer=str(payload["iss"]),
        audience=str(payload["aud"]),
        jti=jti,
        customer=customer,
        issued_at=issued_at,
        expires_at=expires_at,
        not_before=not_before,
        key_id=kid,
    )
    request.state.studio_admin_principal = principal
    StudioAdminAccessAuditRepository(session).append(
        actor_id=principal.actor_id,
        actor_roles=principal.roles,
        actor_permissions=principal.permissions,
        source=principal.source,
        jti=principal.jti,
        correlation_id=request.state.correlation_id,
        source_ip=source_ip,
        path=request.url.path,
        method=request.method,
    )
    return principal


def require_studio_admin_permission(required_permission: str):
    def _dependency(principal: StudioAdminPrincipal = Depends(verify_studio_admin_token)) -> StudioAdminPrincipal:
        if required_permission not in principal.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient Growth permissions.")
        return principal

    return _dependency


def encrypt_contact_value(value: str) -> str:
    key = sha256(get_settings().contact_encryption_key.encode("utf-8")).digest()
    payload = value.encode("utf-8")
    encrypted = bytes(payload[index] ^ key[index % len(key)] for index in range(len(payload)))
    return urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_contact_value(value: str) -> str:
    key = sha256(get_settings().contact_encryption_key.encode("utf-8")).digest()
    payload = urlsafe_b64decode(value.encode("ascii"))
    decrypted = bytes(payload[index] ^ key[index % len(key)] for index in range(len(payload)))
    return decrypted.decode("utf-8")


def hash_review_token(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def sha256_hexdigest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
