import base64
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.application.services.growth_article_media import attach_illustration
from app.core.config import get_settings
from app.domain.errors import CampaignPublicationForbiddenError


def prepare_publication_media(asset, connector, html: str, *, correlation_id: str) -> tuple[str, str | None]:
    image = dict((asset.results or {}).get("image") or {})
    if not image:
        if "/studio-simple/assets/" in html:
            raise CampaignPublicationForbiddenError("Private Growth media cannot be published.")
        return html, None
    root = Path(__file__).resolve().parents[3]
    directory = (root / get_settings().growth_media_storage_dir).resolve()
    file = (root / str(image.get("storage_path") or "")).resolve()
    if directory not in file.parents or not file.is_file() or file.stat().st_size > 12582912:
        raise CampaignPublicationForbiddenError("Article illustration is unavailable for transfer.")
    raw = file.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    destination = connector.config.base_url
    cache = dict(asset.results.get("publication_media") or {})
    imported = dict(cache.get(destination) or {})
    if imported.get("sha256") != sha:
        imported = connector.import_media({"sha256": sha, "content_base64": base64.b64encode(raw).decode()}, correlation_id=correlation_id)
        if imported.get("sha256") != sha or not imported.get("public_url"):
            raise CampaignPublicationForbiddenError("Destination did not confirm the illustration transfer.")
        cache[destination] = imported
        asset.results = {**asset.results, "publication_media": cache}
    target, public = urlsplit(destination), urlsplit(str(imported['public_url']))
    if (public.scheme, public.netloc) != (target.scheme, target.netloc) or not public.path.startswith('/uploads/growth/') or public.query or public.fragment:
        raise CampaignPublicationForbiddenError("Destination returned an invalid illustration URL.")
    soup = BeautifulSoup(attach_illustration(html, asset_id=asset.id, alt=str(image.get("alt_text") or asset.title), placement=image.get("placement", "after_intro")), "html.parser")
    for element in soup.find_all("img", src=f"/studio-simple/assets/{asset.id}/image"):
        element["src"] = imported["public_url"]
    if any('/studio-simple/assets/' in element.get('src','') or '/admin/growth/' in element.get('src','') for element in soup.find_all('img')):
        raise CampaignPublicationForbiddenError('Private Growth illustrations cannot remain in published HTML.')
    return str(soup), imported["public_url"]
