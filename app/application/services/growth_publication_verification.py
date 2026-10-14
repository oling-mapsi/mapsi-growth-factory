import hashlib
from datetime import datetime, UTC
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app.domain.errors import ExternalConnectorError


def matches_published_version(publication, asset, publisher_type: str) -> bool:
    return bool(publication and publication.publication_status == 'PUBLISHED' and publication.content_hash == asset.content_hash and publication.published_content_version == asset.content_version and publication.publication_mode_executed == 'live' and publication.publisher_type == publisher_type)


def verify_publication(connector, asset, public_url: str) -> dict:
    base = getattr(connector.config, 'site_base_url', None) or connector.config.public_base_url
    origin, target = urlsplit(base), urlsplit(public_url)
    if (target.scheme, target.netloc) != (origin.scheme, origin.netloc) or target.path in {'', '/'} or target.query or target.fragment:
        raise ExternalConnectorError('Destination publication URL is invalid; publication has not been verified.')
    try:
        page = connector.client.get(public_url, headers={'Accept':'text/html'}, follow_redirects=False)
        if page.status_code != 200:
            raise ExternalConnectorError('Published article is not publicly accessible; verification must be resumed without republishing.')
        soup = BeautifulSoup(page.text,'html.parser')
        language = soup.find('html')
        if not language or language.get('lang','').split('-')[0] != (asset.locale or 'fr-FR').split('-')[0]:
            raise ExternalConnectorError('Destination did not render the requested article language.')
        heading = soup.find('h1')
        if not heading or heading.get_text(' ',strip=True) != asset.title:
            raise ExternalConnectorError('Destination did not render the approved article title.')
        expected_html = getattr(asset, 'content_html', None) or getattr(asset, 'body', '')
        expected_text = ' '.join(BeautifulSoup(expected_html,'html.parser').stripped_strings)
        rendered_body = soup.select_one('article.oling-resource-content') or soup.select_one('article.resource-card') or soup.find('article')
        if expected_text and (rendered_body is None or ' '.join(rendered_body.stripped_strings) != expected_text):
            raise ExternalConnectorError('Destination body differs from the approved article.')
        canonical = soup.find('link',attrs={'rel':'canonical'})
        if not canonical or canonical.get('href','').rstrip('/') != public_url.rstrip('/'):
            raise ExternalConnectorError('Published article canonical does not match its actual URL.')
        if 'noindex' in page.headers.get('x-robots-tag','').lower():
            raise ExternalConnectorError('Published article is not indexable.')
        robots = soup.find('meta',attrs={'name':'robots'})
        if robots and 'noindex' in robots.get('content','').lower():
            raise ExternalConnectorError('Published article is not indexable.')
        image = dict((asset.results or {}).get('image') or {})
        if image:
            transferred = dict((asset.results or {}).get('publication_media') or {}).get(connector.config.base_url) or {}
            image_url = transferred.get('public_url','')
            rendered = soup.find('img',src=image_url)
            if not image_url or not rendered or not rendered.get('alt','').strip():
                raise ExternalConnectorError('Destination did not render the retained illustration with alternative text.')
            media = connector.client.get(image_url,follow_redirects=False)
            if media.status_code != 200 or not media.headers.get('content-type','').startswith('image/') or hashlib.sha256(media.content).hexdigest() != transferred.get('sha256'):
                raise ExternalConnectorError('Published illustration is inaccessible or differs from the retained image.')
        return {'page_http':200,'canonical':public_url,'image_verified':bool(image),'verified_at':datetime.now(UTC).isoformat()}
    except httpx.HTTPError as exc:
        raise ExternalConnectorError('Public article verification is unavailable; do not repeat the publication.') from exc
