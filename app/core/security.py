import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings

basic_auth = HTTPBasic()


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
