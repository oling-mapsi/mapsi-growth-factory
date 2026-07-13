import base64
from datetime import UTC, datetime, timedelta
import json
import subprocess
import tempfile
from uuid import uuid4

from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.errors import ExternalConnectorError
from app.domain.entities import (
    AudienceSegment,
    CampaignReview,
    CampaignRun,
    ContentAsset,
    OlingNewsPublication,
    SourceEvidence,
)
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.db.models import StudioAdminAccessAuditModel
from app.infrastructure.connectors.oling import OlingConnector
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository

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

PRIVATE_KEY_2 = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCjREYssnbrpqHK
ZN7Xo32ZXB3CEbEqJHRzWFFsZQ/36/VUZ+FdNOCUXUQqoFJK3hQBhH3tnP0AfyII
U2De4wlZBlzOMMGxuz3ZxEFxh2iGpEOLwwG019A0b16OpK+JI7fNPSVwWU7nS2Tj
NWbzgQtNkLzexeGqVcxVnFll0R3swiGLumPM5mRQ9Pf3kQRcG3IXRctrj+NbmgQc
/P7LN4EZ7Av3lqGsrmbXTil8L2nequgQk623ROxeQgq6NHPdJnBc9eWLrU1TMQO3
uaaS7eDImY2u6qZJ+Hi+wGhKuRWDdxKpUiDRDmr6z/K93+plhbDoy5r/ZJlYCt14
gqt/T613AgMBAAECggEAJI4JTkGpCasV53x9PnfPC9LJoOWYLrDZ1+eK14OrNx3A
IKVfmqBXtjBJrmeV9UhS32IcVeLD7OQKKSYN9umLcsDPb6UQASzEtOjRpEsmlprZ
usWvMJ/vcIYM/FAYM1LpeMz7gHOmjHfff1W6FsQqVTQWbaSNmbc7GGH4zCitlBAp
nrJ4yLf819B2BabUkqRODgEjr/xCxBKoYloYJtKwD4TNIr3eM5zHSh3hywwv6Yho
OnRL4FTR6TFuwRRQ67D2JJLsjUW41Fh0F7X4lCZsKubUrvb7039WHwuSEJdXK3o8
5REaPNJK68YcbsXIfkAeUCdDHvaGgjX58ZD0nUtpdQKBgQDSouaCeFRXlZjBj091
yzGTtEYyLy62v86pDptIXaTU7PUA+497pcyG9De4cxbqE7QraH9Nh9Vk23Jpqpf3
ZBmRJhz+osWW8s39e/2thdXR9nNG30uEKHA7otwaE08lT4XJyDuc7p/kKScQpigR
o2kR+e5NKNtH1JQwntGzA6togwKBgQDGbblhIXlTu8hHSx1KZQm2tUov+IFVFBR7
rA3WwfbMsTGd1sVioJphf5H/pwnYS28ERsoKHHWR/v0Ybd1Dx9Tl4wrQYg6XCGiH
ny+7xvfULYZwlNDH302A1oe93Kr9zjkJCZk8YbYoSwrm+swE08qzN+/+PB2Yk8+m
M9jv7gvM/QKBgGNwKfgwDEkow2ulVzLZ0TbUpUrtwVTe6hYfYilgo/8tOmDTYaJS
3GJdiqyWEJxC3wybEXYtiQ1LGBFQStussvE2F/wSJcukJqDjVxgDFbVAbp1nrwPd
/1X4BYZ91SBdEWD4GUR11p/k2Z9fgY0KIwEsh1Z/0j1v2uG1KHQlaFc3AoGAW56G
HecK0jK+QszX9WW5mncSjhu7+8CNxJyotyRQBCs8sZhdAzEMl0AD9Xr2/Lu3ws28
s/Z4ArUtv33a0FUQZCT09UqRWgMz4IsLyzQPchSjIpBT5jWg34AupOeivBXgF+Aq
tMqZBPnBSu06DnCMAzwsv8KaF70H/8GoxP+wyzECgYBBUMwWuwxJ0zU3Lp9VUJj0
Z7CF3JVrcY+CZsJwkLpIHn74iF7yNT4oupq81umCDjw7ODsMaAntmplwMgPZD8Ay
rA2vEWw/mv1Cw+iqxDgXUkarm6mCWOcft6cVmADtjryQysAjwkeIQXbco2JW5TVY
0Tlu6ZKiVXODAe9EcbAdOQ==
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
    private_key: str | None = None,
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
        private_key_file.write(private_key or (PRIVATE_KEY_2 if kid == "studio-k2" else PRIVATE_KEY_1))
        private_key_file.flush()
        message_file.write(signing_input.encode("ascii"))
        message_file.flush()
        result = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                private_key_file.name,
                "-out",
                signature_file.name,
                message_file.name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        signature_file.seek(0)
        signature = signature_file.read()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"
    return {"Authorization": f"Bearer {token}"}


def seed_admin_dataset(session) -> tuple[CampaignRun, ContentAsset]:
    campaigns = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    review_repository = ReviewPortalRepository(session)
    review_service = ReviewPortalService(campaigns, review_repository, audit)

    campaign = CampaignRun(name="Studio Campaign", objective="feature_adoption", status=CampaignStatus.PUBLISHED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="admins", description="Admins"))
    campaign.source_evidences.append(
        SourceEvidence(
            campaign_run_id=campaign.id,
            source_system="github",
            reference="MAPSI-1",
            payload={
                "title": "PR 42",
                "summary": "Ajout d'une API admin",
                "confidence_level": "high",
                "url": "https://github.com/oling-mapsi/mapsi-v6/pull/42",
            },
        )
    )
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="website_article",
        channel="oling",
        title="Studio Article",
        content_html="<p>Studio body</p>",
        content_text="Studio body",
        excerpt="Studio excerpt",
        audience_segment_id=campaign.audience_segments[0].id,
        status=AssetStatus.PUBLISHED,
        published_at=datetime.now(UTC),
        external_publication_id="oling-42",
        external_publication_url="https://www.oling.fr/ressources/studio-article",
        results={
            "preview_url": "https://preview.oling.test/studio-article",
            "publication_mode_requested": "publish",
            "publication_mode_executed": "live",
            "publisher_type": "oling_api",
            "publication_status": "PUBLISHED",
        },
    )
    asset.ensure_content_hash()
    asset.approved_content_hash = asset.content_hash
    asset.approved_by = "approver"
    asset.approved_at = datetime.now(UTC)
    campaign.content_assets.append(asset)
    campaign = campaigns.add(campaign)

    review_repository.save_review(
        CampaignReview(
            campaign_run_id=campaign.id,
            theme=campaign.name,
            objective=campaign.objective,
            segment_id=campaign.audience_segments[0].id,
            segment_label=campaign.audience_segments[0].name,
            audience_volume=21,
            evidence_ids=[campaign.source_evidences[0].id],
            email_subject="Studio subject",
            email_preheader="Studio preheader",
            email_html="<p>Studio body</p>",
            email_text="Studio body",
            quality_control={"passed": True, "score": 96},
            proposed_at=datetime.now(UTC),
            content_version=asset.content_version,
            approved_content_hash=review_service.content_hash(
                CampaignReview(
                    campaign_run_id=campaign.id,
                    theme=campaign.name,
                    objective=campaign.objective,
                    segment_id=campaign.audience_segments[0].id,
                    segment_label=campaign.audience_segments[0].name,
                    audience_volume=21,
                    evidence_ids=[campaign.source_evidences[0].id],
                    email_subject="Studio subject",
                    email_preheader="Studio preheader",
                    email_html="<p>Studio body</p>",
                    email_text="Studio body",
                    quality_control={"passed": True, "score": 96},
                    proposed_at=datetime.now(UTC),
                    content_version=asset.content_version,
                )
            ),
            approved_audience_hash="audience-hash",
            approved_by="approver",
            approved_at=datetime.now(UTC),
        )
    )
    OlingNewsPublicationRepository(session).save(
        OlingNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            status="published",
            mode="live",
            publication_mode_requested="publish",
            publication_mode_executed="live",
            publisher_type="oling_api",
            publication_status="PUBLISHED",
            idempotency_key="studio-oling-1",
            preview_url="https://preview.oling.test/studio-article",
            public_url=asset.external_publication_url,
            public_slug="studio-article",
            published_content_version=asset.content_version,
            published_at=asset.published_at,
            metrics={"published_revision_number": 1},
        )
    )
    audit.append(campaign.id, "review.approved", {"actor": "approver"})
    audit.append(campaign.id, "campaign.oling_published", {"asset_id": asset.id, "external_id": asset.external_publication_id})
    return campaigns.get(campaign.id), campaigns.get(campaign.id).content_assets[0]


def seed_reviewable_admin_dataset(session, *, quality_passed: bool = True) -> tuple[CampaignRun, ContentAsset]:
    campaigns = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    review_repository = ReviewPortalRepository(session)
    review_service = ReviewPortalService(campaigns, review_repository, audit)

    campaign = CampaignRun(name="Reviewable Campaign", objective="feature_adoption", status=CampaignStatus.GENERATED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="reviewers", description="Reviewers"))
    campaign.source_evidences.append(
        SourceEvidence(
            campaign_run_id=campaign.id,
            source_system="github",
            reference="MAPSI-2",
            payload={"title": "PR 84", "summary": "Studio write API", "confidence_level": "high"},
        )
    )
    first_asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="website_article",
        channel="oling",
        title="Draft Article",
        content_html="<p>Draft body</p>",
        content_text="Draft body",
        excerpt="Draft excerpt",
        audience_segment_id=campaign.audience_segments[0].id,
        status=AssetStatus.READY_FOR_REVIEW,
    )
    first_asset.ensure_content_hash()
    second_asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="website_article",
        channel="oling",
        title="Approved Neighbor",
        content_html="<p>Approved body</p>",
        content_text="Approved body",
        excerpt="Approved excerpt",
        audience_segment_id=campaign.audience_segments[0].id,
        status=AssetStatus.APPROVED,
    )
    second_asset.ensure_content_hash()
    second_asset.approved_content_hash = second_asset.content_hash
    second_asset.approved_by = "reviewer-2"
    second_asset.approved_at = datetime.now(UTC)
    campaign.content_assets.extend([first_asset, second_asset])
    campaign = campaigns.add(campaign)
    review_repository.save_review(
        CampaignReview(
            campaign_run_id=campaign.id,
            theme=campaign.name,
            objective=campaign.objective,
            segment_id=campaign.audience_segments[0].id,
            segment_label=campaign.audience_segments[0].name,
            audience_volume=11,
            evidence_ids=[campaign.source_evidences[0].id],
            email_subject=first_asset.title,
            email_preheader=first_asset.excerpt,
            email_html=first_asset.content_html or "",
            email_text=first_asset.content_text,
            quality_control={"passed": quality_passed, "score": 91 if quality_passed else 12},
            proposed_at=datetime.now(UTC),
            content_version=max(item.content_version for item in campaign.content_assets),
            approved_content_hash=review_service.content_hash(
                CampaignReview(
                    campaign_run_id=campaign.id,
                    theme=campaign.name,
                    objective=campaign.objective,
                    segment_id=campaign.audience_segments[0].id,
                    segment_label=campaign.audience_segments[0].name,
                    audience_volume=11,
                    evidence_ids=[campaign.source_evidences[0].id],
                    email_subject=first_asset.title,
                    email_preheader=first_asset.excerpt,
                    email_html=first_asset.content_html or "",
                    email_text=first_asset.content_text,
                    quality_control={"passed": quality_passed},
                    proposed_at=datetime.now(UTC),
                    content_version=max(item.content_version for item in campaign.content_assets),
                )
            ) if quality_passed else "",
            approved_audience_hash="audience-reviewable" if quality_passed else "",
            approved_by="reviewer" if quality_passed else "",
            approved_at=datetime.now(UTC) if quality_passed else None,
        )
    )
    saved = campaigns.get(campaign.id)
    assert saved is not None
    return saved, saved.content_assets[0]


def seed_publishable_oling_asset(session, *, approved: bool = True, hash_matches: bool = True) -> tuple[CampaignRun, ContentAsset]:
    campaigns = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    review_repository = ReviewPortalRepository(session)
    review_service = ReviewPortalService(campaigns, review_repository, audit)

    campaign = CampaignRun(name="Publishable Campaign", objective="feature_adoption", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="publishers", description="Publishers"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="github", reference="MAPSI-3"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="website_article",
        channel="oling",
        title="Ready Article",
        content_html="<p>Ready body</p>",
        content_text="Ready body",
        excerpt="Ready excerpt",
        audience_segment_id=campaign.audience_segments[0].id,
        status=AssetStatus.APPROVED if approved else AssetStatus.READY_FOR_REVIEW,
    )
    asset.ensure_content_hash()
    if approved:
        asset.approved_content_hash = asset.content_hash if hash_matches else "stale-hash"
        asset.approved_by = "approver"
        asset.approved_at = datetime.now(UTC)
    campaign.content_assets.append(asset)
    campaign = campaigns.add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        theme=campaign.name,
        objective=campaign.objective,
        segment_id=campaign.audience_segments[0].id,
        segment_label=campaign.audience_segments[0].name,
        audience_volume=7,
        evidence_ids=[campaign.source_evidences[0].id],
        email_subject=asset.title,
        email_preheader=asset.excerpt,
        email_html=asset.content_html or "",
        email_text=asset.content_text,
        quality_control={"passed": True},
        proposed_at=datetime.now(UTC),
        content_version=asset.content_version,
    )
    review.approved_content_hash = review_service.content_hash(review)
    review.approved_audience_hash = review_service.audience_hash(review)
    review.approved_by = "approver"
    review.approved_at = datetime.now(UTC)
    review_repository.save_review(review)
    saved = campaigns.get(campaign.id)
    assert saved is not None
    return saved, saved.content_assets[0]


def seed_publishable_linkedin_asset(session) -> tuple[CampaignRun, ContentAsset]:
    campaign, _ = seed_publishable_oling_asset(session)
    campaigns = SqlAlchemyCampaignRepository(session)
    stored = campaigns.get(campaign.id)
    assert stored is not None
    linkedin = ContentAsset(
        campaign_run_id=stored.id,
        asset_type="linkedin_company_post",
        channel="linkedin",
        title="LinkedIn Ready",
        content_text="LinkedIn Ready",
        audience_segment_id=stored.audience_segments[0].id,
        status=AssetStatus.APPROVED,
    )
    linkedin.ensure_content_hash()
    linkedin.approved_content_hash = linkedin.content_hash
    linkedin.approved_by = "approver"
    linkedin.approved_at = datetime.now(UTC)
    stored.content_assets.append(linkedin)
    saved = campaigns.save(stored)
    return saved, next(item for item in saved.content_assets if item.channel == "linkedin")


def seed_publishable_mapsi_site_asset(session, *, approved: bool = True, hash_matches: bool = True) -> tuple[CampaignRun, ContentAsset]:
    campaign, _ = seed_publishable_oling_asset(session, approved=approved, hash_matches=hash_matches)
    campaigns = SqlAlchemyCampaignRepository(session)
    stored = campaigns.get(campaign.id)
    assert stored is not None
    asset = ContentAsset(
        campaign_run_id=stored.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title="Ready MAPSI Article",
        content_html="<p>Ready MAPSI body</p>",
        content_text="Ready MAPSI body",
        excerpt="Ready MAPSI excerpt",
        audience_segment_id=stored.audience_segments[0].id,
        status=AssetStatus.APPROVED if approved else AssetStatus.READY_FOR_REVIEW,
    )
    asset.ensure_content_hash()
    if approved:
        asset.approved_content_hash = asset.content_hash if hash_matches else "stale-hash"
        asset.approved_by = "approver"
        asset.approved_at = datetime.now(UTC)
    stored.content_assets.append(asset)
    saved = campaigns.save(stored)
    return saved, next(item for item in saved.content_assets if item.channel == "mapsi_site")


def test_studio_admin_campaigns_returns_summary_with_correlation_and_etag(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get(
        "/api/admin/v1/campaigns",
        headers={**auth_headers(), "X-Correlation-ID": "studio-corr-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["correlation_id"] == "studio-corr-1"
    assert payload["pagination"]["total"] == 1
    assert payload["data"][0]["title"] == "Studio Campaign"
    assert payload["data"][0]["assets_published"] == 1
    assert response.headers["etag"]
    access_audit = session.query(StudioAdminAccessAuditModel).order_by(StudioAdminAccessAuditModel.created_at.desc()).first()
    assert access_audit is not None
    assert access_audit.actor_id == "studio-user-1"
    assert access_audit.source == "mapsi-studio"
    assert access_audit.correlation_id == "studio-corr-1"


def test_studio_admin_asset_endpoints_return_sanitized_payloads(client, session) -> None:
    _, asset = seed_admin_dataset(session)

    asset_response = client.get(f"/api/admin/v1/assets/{asset.id}", headers=auth_headers(jti=str(uuid4())))
    evidence_response = client.get(f"/api/admin/v1/assets/{asset.id}/evidence", headers=auth_headers(jti=str(uuid4())))
    publication_response = client.get(f"/api/admin/v1/assets/{asset.id}/publication", headers=auth_headers(jti=str(uuid4())))

    assert asset_response.status_code == 200
    asset_payload = asset_response.json()["data"]
    assert asset_payload["channel"] == "oling"
    assert asset_payload["preview_available"] is True
    assert asset_payload["publication_available"] is True
    assert asset_payload["public_url"] == "https://www.oling.fr/ressources/studio-article"
    assert "content_html" not in asset_payload
    assert "email" not in str(asset_payload).lower()

    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()["data"][0]
    assert evidence_payload["source_type"] == "github"
    assert evidence_payload["confidence_level"] == "high"
    assert evidence_payload["link"].startswith("https://github.com/")

    assert publication_response.status_code == 200
    publication_payload = publication_response.json()["data"]
    assert publication_payload["publication_status"] == "PUBLISHED"
    assert publication_payload["publication_mode_executed"] == "live"
    assert publication_payload["idempotency_key"] == "studio-oling-1"

    versions_response = client.get(f"/api/admin/v1/assets/{asset.id}/versions", headers=auth_headers(jti=str(uuid4())))
    assert versions_response.status_code == 200
    assert versions_response.json()["data"][0]["content_html"] == "<p>Studio body</p>"


def test_studio_admin_filters_and_not_modified(client, session) -> None:
    _, asset = seed_admin_dataset(session)

    first = client.get("/api/admin/v1/campaigns?published=true&channel=oling", headers=auth_headers(jti=str(uuid4())))
    second = client.get(
        "/api/admin/v1/campaigns?published=true&channel=oling",
        headers={**auth_headers(jti=str(uuid4())), "If-None-Match": first.headers["etag"]},
    )
    preview = client.get(f"/api/admin/v1/assets/{asset.id}/preview", headers=auth_headers(jti=str(uuid4())))

    assert first.status_code == 200
    assert first.json()["pagination"]["total"] == 1
    assert second.status_code == 304
    assert preview.status_code == 200
    assert preview.json()["data"]["available"] is True
    assert preview.json()["data"]["preview_url"].startswith("https://preview.oling.test/")


def test_studio_admin_audit_and_health_routes(client, session) -> None:
    seed_admin_dataset(session)

    audit_response = client.get(
        "/api/admin/v1/audit-events?event_type=campaign.oling_published",
        headers=auth_headers(roles=["ROLE_GROWTH_AUDIT"], jti=str(uuid4())),
    )
    export_response = client.get(
        "/api/admin/v1/audit-events/export.csv?event_type=campaign.oling_published",
        headers=auth_headers(roles=["ROLE_GROWTH_AUDIT"], jti=str(uuid4())),
    )
    health_response = client.get("/api/admin/v1/health", headers=auth_headers(jti=str(uuid4())))

    assert audit_response.status_code == 200
    assert audit_response.json()["pagination"]["total"] == 1
    event = audit_response.json()["data"][0]
    assert event["event_type"] == "campaign.oling_published"
    assert event["event_id"]
    assert event["campaign_id"]
    assert event["metadata"]["external_id"] == "oling-42"
    assert event["integrity_ok"] is True
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")
    assert "campaign.oling_published" in export_response.text
    assert health_response.status_code == 200
    assert health_response.json()["data"]["status"] == "ok"


def test_studio_admin_rejects_missing_token(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns")

    assert response.status_code == 401


def test_studio_admin_rejects_invalid_signature(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(private_key=PRIVATE_KEY_2, kid="studio-k1"))

    assert response.status_code == 401


def test_studio_admin_rejects_wrong_issuer(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(issuer="other-issuer"))

    assert response.status_code == 401


def test_studio_admin_rejects_wrong_audience(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(audience="other-audience"))

    assert response.status_code == 401


def test_studio_admin_rejects_expired_token(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(expires_delta_seconds=-60))

    assert response.status_code == 401


def test_studio_admin_rejects_future_not_before(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(not_before_delta_seconds=120))

    assert response.status_code == 401


def test_studio_admin_rejects_insufficient_role(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get(
        "/api/admin/v1/audit-events",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert response.status_code == 403


def test_studio_admin_accepts_rotated_key(client, session) -> None:
    seed_admin_dataset(session)

    response = client.get("/api/admin/v1/campaigns", headers=auth_headers(kid="studio-k2", jti=str(uuid4())))

    assert response.status_code == 200


def test_studio_admin_rejects_disallowed_algorithm(client, session) -> None:
    seed_admin_dataset(session)
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","kid":"studio-k1","typ":"JWT"}').decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "iss": "mapsi-studio",
                "aud": "mapsi-growth-admin",
                "sub": "studio-user-1",
                "roles": ["ROLE_GROWTH_REVIEW"],
                "customer": "oling-internal",
                "iat": int(datetime.now(UTC).timestamp()),
                "nbf": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(seconds=60)).timestamp()),
                "jti": str(uuid4()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    token = f"{header}.{payload}.signature"

    response = client.get("/api/admin/v1/campaigns", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_studio_admin_rejects_replay_attempt(client, session) -> None:
    seed_admin_dataset(session)
    replay_jti = str(uuid4())
    headers = auth_headers(jti=replay_jti)

    first = client.get("/api/admin/v1/campaigns", headers=headers)
    second = client.get("/api/admin/v1/campaigns", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409


def test_studio_admin_rejects_public_review_token(client, session) -> None:
    _, _, token = __import__("tests.integration.test_review_portal", fromlist=["seed_review"]).seed_review(session)

    response = client.get("/api/admin/v1/campaigns", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_studio_admin_can_be_disabled(client, session, monkeypatch) -> None:
    seed_admin_dataset(session)
    monkeypatch.setenv("STUDIO_ADMIN_API_ENABLED", "false")
    get_settings.cache_clear()
    try:
        response = client.get("/api/admin/v1/campaigns", headers=auth_headers(jti=str(uuid4())))
    finally:
        monkeypatch.setenv("STUDIO_ADMIN_API_ENABLED", "true")
        get_settings.cache_clear()

    assert response.status_code == 503


def test_studio_admin_write_routes_enforce_permissions(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session)

    response = client.post(
        f"/api/admin/v1/assets/{asset.id}/approve",
        json={"expected_version": asset.content_version, "comment": "approve"},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert response.status_code == 403


def test_studio_admin_rejects_version_conflict_on_draft_update(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session)

    response = client.put(
        f"/api/admin/v1/assets/{asset.id}/draft",
        json={"expected_version": asset.content_version + 1, "title": "Updated title", "comment": "manual fix"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert response.status_code == 409


def test_studio_admin_blocks_double_approval(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session)

    first = client.post(
        f"/api/admin/v1/assets/{asset.id}/approve",
        json={"expected_version": asset.content_version, "comment": "looks good"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )
    second = client.post(
        f"/api/admin/v1/assets/{asset.id}/approve",
        json={"expected_version": asset.content_version, "comment": "looks good"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_studio_admin_edit_after_approval_invalidates_only_modified_asset(client, session) -> None:
    campaign, asset = seed_reviewable_admin_dataset(session)
    approve = client.post(
        f"/api/admin/v1/assets/{asset.id}/approve",
        json={"expected_version": asset.content_version, "comment": "approved"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )
    assert approve.status_code == 200

    edited = client.put(
        f"/api/admin/v1/assets/{asset.id}/draft",
        json={"expected_version": asset.content_version, "title": "Edited title", "content_html": "<p>Edited</p>", "content_text": "Edited", "comment": "rewrite"},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert edited.status_code == 200
    payload = edited.json()["data"]
    assert payload["status"] == "READY_FOR_REVIEW"
    assert payload["approved_content_hash"] == ""
    refreshed = SqlAlchemyCampaignRepository(session).get(campaign.id)
    assert refreshed is not None
    other_asset = next(item for item in refreshed.content_assets if item.id != asset.id)
    assert other_asset.status is AssetStatus.APPROVED
    assert other_asset.approved_content_hash == other_asset.content_hash


def test_studio_admin_reject_and_request_changes_require_comment_and_update_status(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session)

    reject = client.post(
        f"/api/admin/v1/assets/{asset.id}/reject",
        json={"expected_version": asset.content_version, "comment": "not acceptable"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert reject.status_code == 200
    assert reject.json()["data"]["status"] == "CHANGES_REQUESTED"

    requested = client.post(
        f"/api/admin/v1/assets/{asset.id}/request-changes",
        json={"expected_version": reject.json()["data"]["version"], "comment": "needs refinement"},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert requested.status_code == 200
    assert requested.json()["data"]["status"] == "CHANGES_REQUESTED"
    assert requested.json()["data"]["version"] == reject.json()["data"]["version"] + 1


def test_studio_admin_write_routes_support_idempotent_replay(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session)
    first_headers = {**auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())), "Idempotency-Key": "studio-approve-1"}
    second_headers = {**auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())), "Idempotency-Key": "studio-approve-1"}
    payload = {"expected_version": asset.content_version, "comment": "approve once"}

    first = client.post(f"/api/admin/v1/assets/{asset.id}/approve", json=payload, headers=first_headers)
    second = client.post(f"/api/admin/v1/assets/{asset.id}/approve", json=payload, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_studio_admin_rejects_invalid_quality_control_on_approval(client, session) -> None:
    _, asset = seed_reviewable_admin_dataset(session, quality_passed=False)

    response = client.post(
        f"/api/admin/v1/assets/{asset.id}/approve",
        json={"expected_version": asset.content_version, "comment": "approve"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert response.status_code == 409


def test_studio_admin_bulk_approve_and_reject_ready_assets(client, session) -> None:
    campaign, asset = seed_reviewable_admin_dataset(session)

    approve = client.post(
        f"/api/admin/v1/campaigns/{campaign.id}/approve-ready-assets",
        json={"comment": "campaign ok"},
        headers={**auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())), "Idempotency-Key": "bulk-approve-1"},
    )

    assert approve.status_code == 200
    assert approve.json()["data"]["decision"] == "APPROVED"
    assert approve.json()["data"]["assets"][0]["id"] == asset.id

    campaign2, asset2 = seed_reviewable_admin_dataset(session)
    reject = client.post(
        f"/api/admin/v1/campaigns/{campaign2.id}/reject-ready-assets",
        json={"comment": "campaign rejected"},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert reject.status_code == 200
    assert reject.json()["data"]["decision"] == "REJECTED"
    assert reject.json()["data"]["assets"][0]["id"] == asset2.id


def test_studio_admin_publication_preview_and_readiness(client, session) -> None:
    _, asset = seed_publishable_oling_asset(session)

    readiness = client.get(
        f"/api/admin/v1/assets/{asset.id}/publication-readiness",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    preview = client.post(
        f"/api/admin/v1/assets/{asset.id}/create-preview",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert readiness.status_code == 200
    assert readiness.json()["data"]["status"] == "ready"
    assert preview.status_code == 200
    assert preview.json()["data"]["requested_action"] == "create_preview"
    assert preview.json()["data"]["preview_url"]
    assert preview.json()["data"]["public_url"] == ""


def test_studio_admin_publication_blocks_non_approved_or_stale_hash(client, session) -> None:
    _, not_approved = seed_publishable_oling_asset(session, approved=False)
    _, stale = seed_publishable_oling_asset(session, approved=True, hash_matches=False)

    first = client.post(
        f"/api/admin/v1/assets/{not_approved.id}/publish",
        json={"idempotency_key": "pub-na-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    second = client.post(
        f"/api/admin/v1/assets/{stale.id}/publish",
        json={"idempotency_key": "pub-stale-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )

    assert first.status_code == 409
    assert second.status_code == 409


def test_studio_admin_publication_blocks_kill_switch_and_channel_flag(client, session, monkeypatch) -> None:
    _, asset = seed_publishable_oling_asset(session)

    monkeypatch.setenv("WORKFLOW_KILL_SWITCH", "true")
    get_settings.cache_clear()
    try:
        kill = client.post(
            f"/api/admin/v1/assets/{asset.id}/publish",
            json={"idempotency_key": "pub-kill-1"},
            headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        )
    finally:
        monkeypatch.setenv("WORKFLOW_KILL_SWITCH", "false")
        get_settings.cache_clear()

    monkeypatch.setenv("PUBLISH_OLING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        disabled = client.post(
            f"/api/admin/v1/assets/{asset.id}/publish",
            json={"idempotency_key": "pub-flag-1"},
            headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        )
    finally:
        monkeypatch.setenv("PUBLISH_OLING_ENABLED", "true")
        get_settings.cache_clear()

    assert kill.status_code == 409
    assert disabled.status_code == 409


def test_studio_admin_publication_is_idempotent_and_exposes_status(client, session) -> None:
    _, asset = seed_publishable_oling_asset(session)
    headers1 = auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4()))
    headers2 = auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4()))

    first = client.post(f"/api/admin/v1/assets/{asset.id}/publish", json={"idempotency_key": "pub-1"}, headers=headers1)
    second = client.post(f"/api/admin/v1/assets/{asset.id}/publish", json={"idempotency_key": "pub-2"}, headers=headers2)
    status_response = client.get(f"/api/admin/v1/assets/{asset.id}/publication-status", headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["external_id"] == second.json()["data"]["external_id"]
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "published"


def test_studio_admin_mapsi_site_publication_preview_publish_and_status(client, session) -> None:
    _, asset = seed_publishable_mapsi_site_asset(session)

    preview = client.post(
        f"/api/admin/v1/assets/{asset.id}/create-preview",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    publish = client.post(
        f"/api/admin/v1/assets/{asset.id}/publish",
        json={"idempotency_key": "mapsi-site-pub-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    replay = client.post(
        f"/api/admin/v1/assets/{asset.id}/publish",
        json={"idempotency_key": "mapsi-site-pub-2"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    status_response = client.get(
        f"/api/admin/v1/assets/{asset.id}/publication-status",
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )

    assert preview.status_code == 200
    assert preview.json()["data"]["preview_url"]
    assert publish.status_code == 200
    assert publish.json()["data"]["publisher"] == "mapsi_site_mock"
    assert replay.status_code == 200
    assert replay.json()["data"]["external_id"] == publish.json()["data"]["external_id"]
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "published"


def test_studio_admin_mapsi_site_publication_blocks_kill_switch_and_flag(client, session, monkeypatch) -> None:
    _, asset = seed_publishable_mapsi_site_asset(session)

    monkeypatch.setenv("WORKFLOW_KILL_SWITCH", "true")
    get_settings.cache_clear()
    try:
        kill = client.post(
            f"/api/admin/v1/assets/{asset.id}/publish",
            json={"idempotency_key": "mapsi-kill-1"},
            headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        )
    finally:
        monkeypatch.setenv("WORKFLOW_KILL_SWITCH", "false")
        get_settings.cache_clear()

    monkeypatch.setenv("PUBLISH_MAPSI_SITE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        disabled = client.post(
            f"/api/admin/v1/assets/{asset.id}/publish",
            json={"idempotency_key": "mapsi-flag-1"},
            headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
        )
    finally:
        monkeypatch.setenv("PUBLISH_MAPSI_SITE_ENABLED", "true")
        get_settings.cache_clear()

    assert kill.status_code == 409
    assert disabled.status_code == 409


def test_studio_admin_publication_handles_remote_error_and_timeout_retry(client, session, monkeypatch) -> None:
    _, error_asset = seed_publishable_oling_asset(session)
    _, timeout_asset = seed_publishable_oling_asset(session)

    def failing_publish(self, external_id: str, *, correlation_id: str):
        raise ExternalConnectorError("remote down")

    original_publish = OlingConnector.publish
    monkeypatch.setattr(OlingConnector, "publish", failing_publish)
    error_response = client.post(
        f"/api/admin/v1/assets/{error_asset.id}/publish",
        json={"idempotency_key": "pub-error-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    monkeypatch.setattr(OlingConnector, "publish", original_publish)

    def timeout_after_remote_publish(self, external_id: str, *, correlation_id: str):
        self._request("POST", f"/api/growth/news/{external_id}/publish", correlation_id=correlation_id)
        raise ExternalConnectorError("timeout after publish")

    monkeypatch.setattr(OlingConnector, "publish", timeout_after_remote_publish)
    timeout_response = client.post(
        f"/api/admin/v1/assets/{timeout_asset.id}/publish",
        json={"idempotency_key": "pub-timeout-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    monkeypatch.setattr(OlingConnector, "publish", original_publish)

    retry_response = client.post(
        f"/api/admin/v1/assets/{error_asset.id}/retry-publication",
        json={"idempotency_key": "pub-retry-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )

    assert error_response.status_code == 409
    assert timeout_response.status_code == 200
    assert timeout_response.json()["data"]["status"] == "published"
    assert retry_response.status_code == 200


def test_studio_admin_publication_schedule_cancel_and_unpublish_unsupported(client, session) -> None:
    _, asset = seed_publishable_oling_asset(session)
    _, linkedin_asset = seed_publishable_linkedin_asset(session)

    schedule = client.post(
        f"/api/admin/v1/assets/{asset.id}/schedule",
        json={"scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    cancel = client.post(
        f"/api/admin/v1/assets/{asset.id}/cancel-publication",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    unsupported = client.post(
        f"/api/admin/v1/assets/{linkedin_asset.id}/unpublish",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )

    assert schedule.status_code == 200
    assert schedule.json()["data"]["status"] == "scheduled"
    assert cancel.status_code == 200
    assert cancel.json()["data"]["status"] == "cancelled"
    assert unsupported.status_code == 409


def test_studio_admin_channel_configuration_requires_configure_permission_and_confirmation(client, session) -> None:
    seed_admin_dataset(session)

    forbidden = client.post(
        "/api/admin/v1/channels/oling/enable",
        json={"confirmation": "CONFIRM"},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    missing_confirmation = client.post(
        "/api/admin/v1/channels/oling/enable",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    enabled = client.post(
        "/api/admin/v1/channels/oling/enable",
        json={"confirmation": "CONFIRM", "expires_in_minutes": 30},
        headers={
            **auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
            "Idempotency-Key": "cfg-enable-1",
        },
    )
    replay = client.post(
        "/api/admin/v1/channels/oling/enable",
        json={"confirmation": "CONFIRM", "expires_in_minutes": 30},
        headers={
            **auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
            "Idempotency-Key": "cfg-enable-1",
        },
    )
    fetched = client.get(
        "/api/admin/v1/channels/oling",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )

    assert forbidden.status_code == 403
    assert missing_confirmation.status_code == 409
    assert enabled.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == enabled.json()
    assert enabled.json()["data"]["feature_enabled"] is True
    assert enabled.json()["data"]["activation_expires_at"] is not None
    assert fetched.status_code == 200
    assert fetched.json()["data"]["feature_enabled"] is True


def test_studio_admin_channel_disable_and_global_kill_switch_affect_publication_rules(client, session) -> None:
    _, asset = seed_publishable_oling_asset(session)

    disabled = client.post(
        "/api/admin/v1/channels/oling/disable",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    blocked_by_channel = client.post(
        f"/api/admin/v1/assets/{asset.id}/publish",
        json={"idempotency_key": "cfg-publish-1"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    reenabled = client.post(
        "/api/admin/v1/channels/oling/enable",
        json={"confirmation": "CONFIRM"},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    global_kill = client.post(
        "/api/admin/v1/global-kill-switch/activate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    blocked_by_global = client.post(
        f"/api/admin/v1/assets/{asset.id}/publish",
        json={"idempotency_key": "cfg-publish-2"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )
    missing_confirmation = client.post(
        "/api/admin/v1/global-kill-switch/deactivate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    cleared = client.post(
        "/api/admin/v1/global-kill-switch/deactivate",
        json={"confirmation": "CONFIRM"},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    published = client.post(
        f"/api/admin/v1/assets/{asset.id}/publish",
        json={"idempotency_key": "cfg-publish-3"},
        headers=auth_headers(roles=["ROLE_GROWTH_PUBLISH"], jti=str(uuid4())),
    )

    assert disabled.status_code == 200
    assert blocked_by_channel.status_code == 409
    assert "PUBLISH_OLING_ENABLED is false" in blocked_by_channel.json()["detail"]["detail"]
    assert reenabled.status_code == 200
    assert global_kill.status_code == 200
    assert global_kill.json()["data"]["active"] is True
    assert blocked_by_global.status_code == 409
    assert "Global publication kill switch is active" in blocked_by_global.json()["detail"]["detail"]
    assert missing_confirmation.status_code == 409
    assert cleared.status_code == 200
    assert cleared.json()["data"]["active"] is False
    assert published.status_code == 200


def test_studio_admin_channel_kill_switch_health_check_and_release_confirmation(client, session) -> None:
    seed_admin_dataset(session)

    health = client.post(
        "/api/admin/v1/channels/linkedin/health-check",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    activated = client.post(
        "/api/admin/v1/channels/linkedin/activate-kill-switch",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    denied = client.post(
        "/api/admin/v1/channels/linkedin/deactivate-kill-switch",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    cleared = client.post(
        "/api/admin/v1/channels/linkedin/deactivate-kill-switch",
        json={"confirmation": "CONFIRM"},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )

    assert health.status_code == 200
    assert health.json()["data"]["last_health_check"] is not None
    assert activated.status_code == 200
    assert activated.json()["data"]["emergency_kill_switch"] is True
    assert denied.status_code == 409
    assert cleared.status_code == 200
    assert cleared.json()["data"]["emergency_kill_switch"] is False


def test_studio_admin_weekly_pack_create_list_and_get(client) -> None:
    created = client.post(
        "/api/admin/v1/weekly-packs",
        json={
            "week_reference": "2026-W29",
            "year": 2026,
            "week_number": 29,
            "pilot_mode": True,
            "force_manual": True,
        },
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )

    assert created.status_code == 200
    payload = created.json()["data"]
    assert payload["week_reference"] == "2026-W29"
    assert payload["pilot_mode"] is True
    assert len(payload["campaign_ids"]) == 3
    assert {item["campaign_type"] for item in payload["campaigns"]} == {"MAPSI_MARKET", "OLING_PRACTICE", "MAPSI_USERS"}

    listed = client.get(
        "/api/admin/v1/weekly-packs",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    fetched = client.get(
        f"/api/admin/v1/weekly-packs/{payload['id']}",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    duplicate = client.post(
        "/api/admin/v1/weekly-packs",
        json={
            "week_reference": "2026-W29",
            "year": 2026,
            "week_number": 29,
            "pilot_mode": False,
            "force_manual": True,
        },
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )

    assert listed.status_code == 200
    assert listed.json()["pagination"]["total"] >= 1
    assert fetched.status_code == 200
    assert fetched.json()["data"]["id"] == payload["id"]
    assert duplicate.status_code == 409


def test_studio_admin_weekly_pack_generate_and_close(client) -> None:
    created = client.post(
        "/api/admin/v1/weekly-packs",
        json={
            "week_reference": "2026-W30",
            "year": 2026,
            "week_number": 30,
            "pilot_mode": True,
            "force_manual": True,
        },
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    pack_id = created.json()["data"]["id"]

    generated = client.post(
        f"/api/admin/v1/weekly-packs/{pack_id}/generate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert generated.status_code == 200
    generated_payload = generated.json()["data"]
    assert generated_payload["generated_at"] is not None
    assert generated_payload["global_summary"]["campaigns_generated"] == 3
    campaigns = {item["campaign_type"]: item for item in generated_payload["campaigns"]}
    assert campaigns["MAPSI_MARKET"]["asset_count"] == 3
    assert campaigns["OLING_PRACTICE"]["asset_count"] == 2
    assert campaigns["MAPSI_USERS"]["asset_count"] == 1
    assert all(item["status"] == "READY_FOR_REVIEW" for item in campaigns.values())

    closed = client.post(
        f"/api/admin/v1/weekly-packs/{pack_id}/close",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )

    assert closed.status_code == 200
    assert closed.json()["data"]["completed_at"] is not None


def test_studio_admin_source_pack_crud_and_validate(client) -> None:
    weekly = client.post(
        "/api/admin/v1/weekly-packs",
        json={"week_reference": "2026-W31", "year": 2026, "week_number": 31, "pilot_mode": True, "force_manual": True},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    weekly_pack_id = weekly.json()["data"]["id"]

    created = client.post(
        "/api/admin/v1/source-packs",
        json={
            "weekly_pack_id": weekly_pack_id,
            "campaign_type": "MAPSI_MARKET",
            "title": "Sources semaine 31",
            "summary": "Base editoriale verifiable",
            "confidentiality_level": "INTERNAL",
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    payload = created.json()["data"]
    source_pack_id = payload["id"]

    assert created.status_code == 200
    assert payload["campaign_type"] == "MAPSI_MARKET"
    assert payload["status"] == "DRAFT"

    updated = client.put(
        f"/api/admin/v1/source-packs/{source_pack_id}",
        json={
            "weekly_pack_id": weekly_pack_id,
            "campaign_type": "MAPSI_MARKET",
            "title": "Sources marche semaine 31",
            "summary": "Synthese ajustee",
            "confidentiality_level": "CLIENT_CONFIDENTIAL",
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    fetched = client.get(
        f"/api/admin/v1/source-packs/{source_pack_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    validated = client.post(
        f"/api/admin/v1/source-packs/{source_pack_id}/validate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["confidentiality_level"] == "CLIENT_CONFIDENTIAL"
    assert fetched.status_code == 200
    assert fetched.json()["data"]["title"] == "Sources marche semaine 31"
    assert validated.status_code == 200
    assert validated.json()["data"]["status"] == "VALIDATED"
    assert validated.json()["data"]["validated_by"] == "studio-user-1"


def test_studio_admin_source_pack_items_and_editorial_preview_apply_redaction_rules(client) -> None:
    weekly = client.post(
        "/api/admin/v1/weekly-packs",
        json={"week_reference": "2026-W32", "year": 2026, "week_number": 32, "pilot_mode": True, "force_manual": True},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    weekly_pack_id = weekly.json()["data"]["id"]
    source_pack = client.post(
        "/api/admin/v1/source-packs",
        json={
            "weekly_pack_id": weekly_pack_id,
            "campaign_type": "OLING_PRACTICE",
            "title": "Sources pratique",
            "summary": "Pack pratique",
            "confidentiality_level": "INTERNAL",
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    source_pack_id = source_pack.json()["data"]["id"]

    created_item = client.post(
        f"/api/admin/v1/source-packs/{source_pack_id}/items",
        json={
            "source_type": "PROJECT_DELIVERABLE",
            "source_reference": "DELIV-32",
            "source_title": "Restitution client",
            "factual_summary": "Acme a reduit le temps de traitement.",
            "usable_facts": ["Acme a reduit le temps de traitement."],
            "anonymized_facts": ["Un client a reduit le temps de traitement."],
            "prohibited_facts": ["Le chiffre exact reste confidentiel."],
            "client_name": "Acme",
            "client_name_usage_authorized": False,
            "confidentiality_level": "CLIENT_CONFIDENTIAL",
            "evidence_quality": "high",
            "manual_input": {
                "project_summary": "Projet d'optimisation",
                "client_problem": "Temps de traitement trop long",
                "oling_method": "Cadre OLING",
                "deliverables_completed": ["Atelier", "Synthese"],
                "observed_results": ["Moins de friction"],
                "lessons_learned": ["Prioriser les cas simples"],
                "desired_cta": "Demander un audit",
            },
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    item_id = created_item.json()["data"]["items"][0]["id"]

    assert created_item.status_code == 200
    assert created_item.json()["data"]["items"][0]["content_hash"] != ""

    updated_item = client.put(
        f"/api/admin/v1/source-packs/{source_pack_id}/items/{item_id}",
        json={
            "source_type": "PROJECT_DELIVERABLE",
            "source_reference": "DELIV-32",
            "source_title": "Restitution client",
            "factual_summary": "Acme a accelere l'adoption.",
            "usable_facts": ["Acme a accelere l'adoption."],
            "anonymized_facts": ["Un client a accelere l'adoption."],
            "prohibited_facts": ["Le chiffre exact reste confidentiel."],
            "client_name": "Acme",
            "client_name_usage_authorized": False,
            "confidentiality_level": "CLIENT_CONFIDENTIAL",
            "evidence_quality": "high",
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    preview = client.get(
        f"/api/admin/v1/source-packs/{source_pack_id}/editorial-preview",
        headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
    )
    deleted = client.delete(
        f"/api/admin/v1/source-packs/{source_pack_id}/items/{item_id}",
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert updated_item.status_code == 200
    assert preview.status_code == 200
    preview_payload = preview.json()["data"]
    assert preview_payload["redaction_summary"]["attachments_sent_to_model"] == 0
    assert any(item["mode"] == "anonymized" for item in preview_payload["allowed_facts"])
    assert any(item["reason"] == "confidential_raw_fact" for item in preview_payload["blocked_facts"])
    assert all("Acme" not in item["fact"] for item in preview_payload["allowed_facts"])
    assert deleted.status_code == 200
    assert deleted.json()["data"]["items"] == []


def test_studio_admin_weekly_pack_generate_uses_oling_practice_builder(client) -> None:
    weekly = client.post(
        "/api/admin/v1/weekly-packs",
        json={"week_reference": "2026-W33", "year": 2026, "week_number": 33, "pilot_mode": True, "force_manual": True},
        headers=auth_headers(roles=["ROLE_GROWTH_CONFIGURE"], jti=str(uuid4())),
    )
    weekly_pack_id = weekly.json()["data"]["id"]
    source_pack = client.post(
        "/api/admin/v1/source-packs",
        json={
            "weekly_pack_id": weekly_pack_id,
            "campaign_type": "OLING_PRACTICE",
            "title": "Sources pratique OLING",
            "summary": "Base pratique",
            "confidentiality_level": "INTERNAL",
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    source_pack_id = source_pack.json()["data"]["id"]
    client.post(
        f"/api/admin/v1/source-packs/{source_pack_id}/items",
        json={
            "source_type": "PROJECT_DELIVERABLE",
            "source_reference": "DELIV-W33",
            "source_title": "Accompagnement ERP",
            "factual_summary": "Projet ERP pour un client",
            "usable_facts": ["Acme a clarifie le pilotage ERP."],
            "anonymized_facts": ["Un client a clarifie le pilotage ERP."],
            "client_name": "Acme",
            "client_name_usage_authorized": False,
            "confidentiality_level": "CLIENT_CONFIDENTIAL",
            "evidence_quality": "high",
            "manual_input": {
                "client_problem": "Le pilotage ERP manquait de cadre.",
                "oling_method": "Cadrage, ateliers et feuille de route.",
                "deliverables_completed": ["Cadrage", "Feuille de route"],
                "observed_results": ["Vision partagee"],
                "lessons_learned": ["Commencer par le cadrage"],
            },
        },
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )
    client.post(
        f"/api/admin/v1/source-packs/{source_pack_id}/validate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_APPROVE"], jti=str(uuid4())),
    )

    generated = client.post(
        f"/api/admin/v1/weekly-packs/{weekly_pack_id}/generate",
        json={},
        headers=auth_headers(roles=["ROLE_GROWTH_REVIEW"], jti=str(uuid4())),
    )

    assert generated.status_code == 200
    campaigns = {item["campaign_type"]: item for item in generated.json()["data"]["campaigns"]}
    oling_practice = campaigns["OLING_PRACTICE"]
    assert oling_practice["asset_count"] == 2
    assert oling_practice["status"] == "READY_FOR_REVIEW"


def test_studio_admin_exposes_pilot_banner_in_dashboard_health_and_channels(client, monkeypatch) -> None:
    monkeypatch.setenv("GROWTH_OPERATION_MODE", "pilot")
    monkeypatch.setenv("PILOT_EMAIL_ALLOWLIST", "pilot@example.test")
    get_settings.cache_clear()
    try:
        dashboard = client.get(
            "/api/admin/v1/dashboard",
            headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
        )
        health = client.get(
            "/api/admin/v1/health",
            headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
        )
        channel = client.get(
            "/api/admin/v1/channels/mapsi_users",
            headers=auth_headers(roles=["ROLE_GROWTH_VIEWER"], jti=str(uuid4())),
        )

        assert dashboard.status_code == 200
        assert dashboard.json()["data"]["operational_mode"] == "pilot"
        assert dashboard.json()["data"]["banner_message"] == "MODE PILOTE"
        assert health.status_code == 200
        assert health.json()["data"]["operational_mode"] == "pilot"
        assert channel.status_code == 200
        assert channel.json()["data"]["operational_mode"] == "pilot"
        assert channel.json()["data"]["banner_message"] == "MODE PILOTE"
    finally:
        monkeypatch.delenv("GROWTH_OPERATION_MODE", raising=False)
        monkeypatch.delenv("PILOT_EMAIL_ALLOWLIST", raising=False)
        get_settings.cache_clear()
