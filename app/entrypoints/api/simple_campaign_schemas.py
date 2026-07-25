from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SimpleCampaignCreateRequest(BaseModel):
    name: str
    campaign_type: str
    theme: str = ""
    selected_channels: list[str] = Field(default_factory=list)


class SimpleCampaignPublishRequest(BaseModel):
    channels: list[str] = Field(default_factory=list)


class SimpleAssetUpdateRequest(BaseModel):
    title: str | None = None
    content_html: str | None = None
    content_text: str | None = None
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
    asset_type: str
    title: str
    content_html: str | None
    content_text: str
    excerpt: str
    call_to_action: str
    illustration_suggestion: str
    status: str
    version: int
    public_url: str
    published_at: datetime | None


class SimpleCampaignResponse(BaseModel):
    id: str
    name: str
    campaign_type: str
    theme: str
    status: str
    selected_channels: list[str]
    created_at: datetime
    updated_at: datetime
    content_assets: list[SimpleAssetResponse]
    publications: list[SimplePublicationResponse]


class OlingThemeCatalogResponse(BaseModel):
    items: list[str]
