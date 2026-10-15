from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SimpleCampaignCreateRequest(BaseModel):
    name: str
    campaign_type: str
    theme: str = ""
    brief: str = ""
    selected_channels: list[str] = Field(default_factory=list)


class SimpleCampaignPublishRequest(BaseModel):
    channels: list[str] = Field(default_factory=list)


class SimpleAssetUpdateRequest(BaseModel):
    title: str | None = None
    content_html: str | None = None
    content_text: str | None = None
    expected_version: int | None = None
    image_placement: str | None = None


class SimpleAssetDecisionRequest(BaseModel):
    comment: str = ""
    expected_version: int | None = None
    confirm_editorial_review: bool = Field(default=False, strict=True)


class SimpleAssetImageRequest(BaseModel):
    visual_brief: str = ""
    expected_version: int | None = None
    source_asset_id: str | None = None


class SimpleAssetSeoGeoRequest(BaseModel):
    expected_version: int | None = None


class SimplePublicationResponse(BaseModel):
    id: str
    channel: str
    external_reference: str
    external_url: str
    published_at: datetime


class SimpleAssetResponse(BaseModel):
    id: str
    channel: str
    locale: str = "fr-FR"
    asset_type: str
    title: str
    content_html: str | None
    content_text: str
    excerpt: str
    call_to_action: str
    illustration_suggestion: str
    image: dict = Field(default_factory=dict)
    seo_geo: dict = Field(default_factory=dict)
    status: str
    version: int
    approved_by: str
    approved_at: datetime | None
    approved_version: int | None
    approved_content_hash: str = ''
    public_url: str
    published_at: datetime | None
    editorial_quality: dict = Field(default_factory=dict)
    quality_blocking: bool = False
    sources: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)


class SimpleCampaignResponse(BaseModel):
    id: str
    name: str
    campaign_type: str
    theme: str
    brief: str
    status: str
    selected_channels: list[str]
    created_at: datetime
    updated_at: datetime
    content_assets: list[SimpleAssetResponse]
    publications: list[SimplePublicationResponse]
    generation: dict | None = None


class OlingThemeCatalogResponse(BaseModel):
    items: list[str]
