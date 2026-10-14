import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup


def words(value: str) -> set[str]:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return set(re.findall(r'[a-z0-9]{3,}', value)) - {'pour','avec','dans','une','les','des','aux','the','and','for','with','para','con','los','las','del','mise','place','sur','article','oling','mapsi'}


class PublicPageCatalog:
    def __init__(self):
        self.directory = Path(__file__).resolve().parents[3] / 'storage/page-catalog'

    def candidates(self, *, channel: str, locale: str, title: str, text: str) -> list[dict]:
        host = 'mapsi.fr' if channel == 'mapsi_site' else 'oling.fr'
        language = 'fr' if channel == 'mapsi_site' else locale[:2]
        query = words(title)
        if 'erp' in query:
            query |= {'amoa','progiciel','cadrage','migration','recette','erp','implementation','implantacion'}
        urls = self._urls(host)
        urls = [url for url in urls if self._language(url) == language]
        ranked = sorted(urls, key=lambda url: len(query & words(urlparse(url).path)), reverse=True)
        pages = []
        candidates = [url for url in ranked[:24] if query & words(urlparse(url).path)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            checked = list(pool.map(lambda url: self._page(url,host,language),candidates))
        for url, page in zip(candidates, checked):
            if page is None:
                continue
            overlap = query & words(page['label']+' '+page['description']+' '+urlparse(page['url']).path)
            if not overlap:
                continue
            anchors = [word for word in re.findall(r'\b[\w-]{3,}\b', text) if words(word) & overlap]
            if not anchors:
                continue
            anchor = next((word for word in anchors if words(word) & {'erp','amoa','progiciel','cadrage','migration','recette'}), anchors[0])
            pages.append({**page,'anchor':anchor,'reason':'Sujet et page concordants : '+', '.join(sorted(overlap)), 'score':len(overlap)})
        pages.sort(key=lambda item: item['score'], reverse=True)
        seen = set()
        return [item for item in pages if not (item['url'] in seen or seen.add(item['url']))][:5]

    def _urls(self, host: str) -> list[str]:
        key = self.directory / (host+'.json')
        if key.is_file() and time.time()-key.stat().st_mtime < 3600:
            return json.loads(key.read_text())
        urls = set()
        pending = [f'https://{host}/sitemap.xml']
        visited = set()
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            while pending and len(visited)<12:
                url = pending.pop(0)
                if url in visited or not self._allowed(url, host): continue
                visited.add(url)
                try:
                    response = client.get(url)
                    if response.status_code != 200 or len(response.content)>4000000: continue
                    root = ElementTree.fromstring(response.content)
                except (httpx.HTTPError, ElementTree.ParseError):
                    continue
                for node in root.iter():
                    if node.tag.rsplit('}',1)[-1] != 'loc' or not node.text: continue
                    link = node.text.strip()
                    if not self._allowed(link,host): continue
                    if root.tag.endswith('sitemapindex'): pending.append(link)
                    else: urls.add(link)
        if urls:
            self.directory.mkdir(parents=True, exist_ok=True)
            key.write_text(json.dumps(sorted(urls)))
        return sorted(urls)

    def _page(self, url: str, host: str, language: str) -> dict | None:
        try:
            response = httpx.get(url, timeout=8, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or len(response.content)>2000000 or 'noindex' in response.headers.get('x-robots-tag','').lower(): return None
        soup = BeautifulSoup(response.text, 'html.parser')
        robots = soup.find('meta', attrs={'name':'robots'})
        if robots and 'noindex' in robots.get('content','').lower(): return None
        html = soup.find('html')
        if not html or html.get('lang','').lower().split('-')[0] != language: return None
        canonical = soup.find('link', attrs={'rel':'canonical'})
        actual = canonical.get('href','') if canonical else ''
        if not self._allowed(actual,host) or self._language(actual) != language: return None
        if urlparse(actual).path.rstrip('/') != urlparse(url).path.rstrip('/'): return None
        heading = soup.find('h1') or soup.find('title')
        if heading is None: return None
        description = soup.find('meta', attrs={'name':'description'})
        return {'label':heading.get_text(' ',strip=True),'url':actual,'final_url':actual,'description':description.get('content','') if description else '', 'status_code':200, 'verification':'verified', 'locale':language}

    def _allowed(self, url: str, host: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme=='https' and parsed.hostname in {host, 'www.'+host} and parsed.path not in {'','/','/fr','/fr/','/en','/en/','/es','/es/'} and not parsed.query and not re.match(r'^/(admin|api|preview|master|studio)(/|$)',parsed.path)

    def _language(self, url: str) -> str:
        path = urlparse(url).path
        return 'en' if path.startswith('/en/') else 'es' if path.startswith('/es/') else 'fr'
