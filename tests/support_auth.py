import base64
from datetime import UTC, datetime, timedelta
import json
import subprocess
import tempfile
from uuid import uuid4


PRIVATE_KEY_1 = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDkPJYGIt5w7lXc
a1iJ6Om8AqPxmPI+rGstC5dfrfEHdekvZoWEgozk+U0SbLQaau8V20U9FO4hiO+O
Rd7sTRjhjLHuJVM7H19byzzAkF1WfNqUvnLY9qaDKBbU2i1Spsw8dFYM2OUbZ/ok
93MQqeOPTsoLOXNw0aexp4FI3RZPmBp5pOFPX3aV9MdXhDktuAdHl4z6XQHzzmQ5
Ba3iscZIsHa9BsMXsaJ+JbTNIhhkTyXjXr1/5mnIiAR696vcJXkXxXBxOa+DilIu
yo3Uc+EPBjziHsc/znu96t0lBK5BAQMlq+zFcak9kJut4Bl+v4KONJw8JNszJJ8l
NUHFbtgdAgMBAAECggEAFZoMYwFK3L/EvaDQAkwv+dJQJ641A1c4qkybY6a9a4TZ
RgS7Ogr3KzbTTh1Jaz9YE1FWZiJvKsULU1kWm8vs68VwE8em7y9tdu0vT1R6mRR7
xbHu1yJ6fmsSxMuaQuU0QGaMZxk3j1anLMzaMFIRY9TDt7iUzgaci2p8szjwWHux
seggNjOn7OsWH1rMrJiwNJbbZuh4i0/S8daILRa2/ZBoPUoQshrHM5obWQElgWVt
sZgSYG9U5HYThqAOldPb1dZQLL18Z4zj4GHICtz1D5ary/mFjPjlOc61oVGoKueP
gjFQ7fChk5vgrUY+TcItj8bw+JobScAozzZjoGxeSwKBgQD0tzvXHgfu8NXS0D8m
GhJuUXNTaY1/OfbTDQqMJhjL6YBtT2VrwKFdWeeCd64xfd+ohdBR4em6sOA+SyGJ
P5TR+WxGapZWaYJ3bGMzOiMznAyyjUe3Akvc1dx9vKu74Pv0h/LEFtHE7yBa8LEv
ceDtJ47CtofCemXvAX3vbW3LowKBgQDuwtLT0x/niUMe/gZY+yvzf+cvSrkfcxSo
rRQ+sMcdwenHwBeAghxbW4GoKoYWqAWjcb9ssJ6Qi9tBBCPsWCjwEk/A95vPXtTx
O/ZZUUH+sm1MO4OHaXBl6LnddNO8n5NEtKZh2mk9p/VLHMx8SCgb9+qZA0n3dLRD
t8Fpi8sJPwKBgEcgGpxjdhrUlNE5BaGlYkX+Fm7f9uhLiJm+6JnjWMGrlFAxC2FO
E5h2UPtynYZ091Sbz/h8mNpSHlr8qzqg6Dg/LmEpCZkEAY+ESTDSbPjLGkWrGnTu
je4ZmoRRGfj5Y0GnYb/sgfujJNxJqLYJez5yiOO++aZkvMvCuz+jpo3RAoGBANm0
ISJuNoAbA23F+Cm4VDoB3N2dR7EqcKLgtj33WIeEodK2D3foq0yN4mpg48TSzdlb
RU0oulxYecINsWe2dxV3zOrJm3N5J7cSkqycUA2Zydkhxut4s7jofFk2Rj6OTmzu
P2uoCB/k/t/PUZDdBl2CL5H3ksEk052PdrbzdV1nAoGAVdjwvx4zpziblkb9BwcB
/wNrYZLBUHtT2xn4hzH3w/wjHoc0EugMnD4fjxaddUj8/S5luqL+9AQkhBesqq+P
aa1h1L6gFsZYuNQpipwk9rz/Y1uKeGEA2giYp2Kkbtuk/9/Br7KRZFy94kmLaAWm
WQQN1vrbgT4QzyX0VBuSXP4=
-----END PRIVATE KEY-----"""


def auth_headers(
    *,
    roles: list[str] | None = None,
    kid: str = "studio-k1",
    jti: str | None = None,
    issuer: str = "mapsi-studio",
    audience: str = "mapsi-growth-admin",
    sub: str = "studio-user-1",
    customer: str = "oling-internal",
    expires_delta_seconds: int = 120,
    not_before_delta_seconds: int = 0,
) -> dict[str, str]:
    now = datetime.now(UTC)
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "roles": roles or ["ROLE_GROWTH_REVIEW"],
        "customer": customer,
        "iat": int(now.timestamp()),
        "nbf": int((now + timedelta(seconds=not_before_delta_seconds)).timestamp()),
        "exp": int((now + timedelta(seconds=expires_delta_seconds)).timestamp()),
        "jti": jti or str(uuid4()),
    }
    signing_input = ".".join(
        [
            base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("="),
        ]
    )
    with tempfile.NamedTemporaryFile("w", delete=True) as private_key_file, tempfile.NamedTemporaryFile("wb", delete=True) as message_file, tempfile.NamedTemporaryFile("rb", delete=True) as signature_file:
        private_key_file.write(PRIVATE_KEY_1)
        private_key_file.flush()
        message_file.write(signing_input.encode("ascii"))
        message_file.flush()
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", private_key_file.name, "-out", signature_file.name, message_file.name],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        signature_file.seek(0)
        signature = signature_file.read()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"
    return {"Authorization": f"Bearer {token}"}
