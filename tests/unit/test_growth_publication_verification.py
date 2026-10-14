from types import SimpleNamespace
import hashlib

import httpx
import pytest

from app.application.services.growth_publication_verification import verify_publication
from app.domain.errors import ExternalConnectorError


@pytest.mark.parametrize('failure',[None,'page','title','canonical','locale','image','checksum','body'])
def test_real_success_requires_rendered_article_and_matching_public_image(failure):
    base='https://recette.invalid'
    raw=b'only-synthetic-image-bytes'
    sha=hashlib.sha256(raw).hexdigest()
    asset=SimpleNamespace(title='Approved ERP',locale='fr-FR',content_html='<p>Approved body</p>',results={'image':{'alt_text':'ERP'},'publication_media':{base:{'public_url':base+'/uploads/growth/image.png','sha256':sha}}})
    def request(req):
        if req.url.path.startswith('/uploads/'):
            return httpx.Response(404 if failure=='image' else 200,content=b'wrong' if failure=='checksum' else raw,headers={'Content-Type':'image/png'})
        canonical=base+'/' if failure=='canonical' else base+'/article'
        title='Wrong article' if failure=='title' else asset.title
        locale='en' if failure=='locale' else 'fr'
        body='<p>Unapproved body</p>' if failure=='body' else asset.content_html
        return httpx.Response(404 if failure=='page' else 200,text=f'<html lang="{locale}"><head><link rel="canonical" href="{canonical}"></head><body><h1>{title}</h1><article>{body}<img src="{base}/uploads/growth/image.png" alt="ERP"></article></body></html>')
    connector=SimpleNamespace(config=SimpleNamespace(base_url=base,site_base_url=base),client=httpx.Client(transport=httpx.MockTransport(request)))
    if failure:
        with pytest.raises(ExternalConnectorError): verify_publication(connector,asset,base+'/article')
    else:
        assert verify_publication(connector,asset,base+'/article')['image_verified'] is True


def test_untrusted_public_url_is_rejected_without_network():
    connector=SimpleNamespace(config=SimpleNamespace(site_base_url='https://recette.invalid'))
    with pytest.raises(ExternalConnectorError):
        verify_publication(connector,None,'https://other.invalid/article')


@pytest.mark.parametrize('version,mode,publisher,expected',[(1,'live','oling_api',True),(2,'live','oling_api',False),(1,'mock','oling_mock',False)])
def test_cached_publication_requires_the_exact_real_published_version(version,mode,publisher,expected):
    from app.application.services.growth_publication_verification import matches_published_version
    asset=SimpleNamespace(content_hash='approved-hash',content_version=version)
    publication=SimpleNamespace(publication_status='PUBLISHED',content_hash='approved-hash',published_content_version=1,publication_mode_executed=mode,publisher_type=publisher)
    assert matches_published_version(publication,asset,'oling_api') is expected
