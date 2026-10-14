from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse
import unicodedata

import httpx
from bs4 import BeautifulSoup, NavigableString
from app.application.services.growth_page_catalog import PublicPageCatalog


@dataclass(frozen=True)
class GrowthSeoGeoResult:
    status: str
    checks: list[dict]
    metadata: dict
    internal_links: list[dict]
    html: str


class GrowthSeoGeoService:
    def __init__(self, catalog=None):
        self.catalog = catalog or PublicPageCatalog()
    OILING_LINKS = {
        "fr-FR": [
            {"label": "Ressources OLING", "url": "https://oling.fr/ressources"},
            {"label": "AMOA SI", "url": "https://oling.fr/amoa-si"},
            {"label": "Contact OLING", "url": "https://oling.fr/contact"},
        ],
        "en-US": [
            {"label": "OLING resources", "url": "https://oling.fr/en/resources"},
            {"label": "Contact OLING", "url": "https://oling.fr/en/contact"},
        ],
        "es-ES": [
            {"label": "Recursos OLING", "url": "https://oling.fr/es/recursos"},
            {"label": "Contacto OLING", "url": "https://oling.fr/es/contacto"},
        ],
    }
    MAPSI_LINKS = [
        {"label": "MAPSI", "url": "https://mapsi.fr/"},
        {"label": "MAPSI logiciel QHSE", "url": "https://mapsi.fr/fr/"},
    ]

    def prepare(self, *, channel: str, title: str, html: str, text: str, image_alt: str = "", locale: str = "fr-FR", public_url: str = "") -> GrowthSeoGeoResult:
        slug = self._slugify(title)
        links = self.catalog.candidates(channel=channel, locale=locale, title=title, text=text)
        enriched_html = self._insert_links(html, links)
        inserted = BeautifulSoup(enriched_html, 'html.parser')
        links = [link for link in links if inserted.find('a',href=link['url'])]
        canonical = public_url.strip() or self._canonical_url(channel=channel, locale=locale, slug=slug)
        metadata = {
            "h1": title,
            "seo_title": title[:70],
            "meta_description": self._summary(text, 155),
            "slug": slug,
            "canonical": canonical,
            "primary_keyword": self._primary_keyword(title),
            "summary": self._summary(text, 260),
            "image_alt": image_alt.strip() or self._localized_image_alt(title, locale),
            "locale": locale,
            "hreflang": [],
            "open_graph": {"title": title[:70], "description": self._summary(text, 155)},
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": title[:110],
                "description": self._summary(text, 155),
            },
        }
        checks = self._checks(title=title, html=enriched_html, text=text, metadata=metadata, links=links, image_alt=metadata["image_alt"])
        status = "READY" if all(item["passed"] for item in checks if item["severity"] == "error") else "NEEDS_FIX"
        return GrowthSeoGeoResult(status=status, checks=checks, metadata=metadata, internal_links=links, html=enriched_html)

    def _verified_links(self, candidates: list[dict]) -> list[dict]:
        verified: list[dict] = []
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            for item in candidates:
                try:
                    response = client.head(item["url"])
                    if response.status_code == 405:
                        response = client.get(item["url"])
                except httpx.HTTPError:
                    continue
                if 200 <= response.status_code < 300:
                    verified.append({**item, "status_code": response.status_code, "final_url": str(response.url)})
        return verified[:4]

    def _insert_links(self, html: str, links: list[dict]) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        for link in links:
            if soup.find('a',href=link['url']): continue
            anchor = link.get('anchor','')
            if not anchor: continue
            for node in list(soup.find_all(string=True)):
                if node.find_parent('a') or node.parent.name not in {'p','li','strong','em'}: continue
                match = re.search(r'\b'+re.escape(anchor)+r'\b',str(node),re.I)
                if not match: continue
                element = soup.new_tag('a',href=link['url'])
                element.string = match.group()
                node.replace_with(NavigableString(str(node)[:match.start()]), element, NavigableString(str(node)[match.end():]))
                break
        return str(soup)

    def _checks(self, *, title: str, html: str, text: str, metadata: dict, links: list[dict], image_alt: str) -> list[dict]:
        return [
            {"code": "title", "label": "Titre editorial", "passed": bool(title.strip()), "severity": "error"},
            {"code": "meta_description", "label": "Meta description", "passed": len(metadata["meta_description"]) >= 80, "severity": "error"},
            {"code": "slug", "label": "Slug lisible", "passed": bool(metadata["slug"]), "severity": "error"},
            {"code": "structure", "label": "Structure H2", "passed": html.count("<h2") >= 2, "severity": "warning"},
            {"code": "internal_links", "label": "Liens internes verifies", "passed": len(links) >= 1, "severity": "error"},
            {"code": "image_alt", "label": "Texte alternatif image", "passed": bool(image_alt.strip()), "severity": "warning"},
            {"code": "json_ld", "label": "Donnees structurees Article", "passed": metadata["json_ld"]["headline"] != "", "severity": "error"},
            {"code": "geo", "label": "Passages structurables IA", "passed": len(text) >= 900 and bool(re.search(r"\b(comment|pourquoi|methode|points?|etapes?|how|why|steps?|como|por que|pasos?)\b", text, re.I)), "severity": "warning"},
            {"code": "canonical", "label": "Canonical valide", "passed": urlparse(metadata["canonical"]).scheme == "https", "severity": "error"},
        ]

    def _summary(self, text: str, limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:limit].rstrip()

    def _primary_keyword(self, title: str) -> str:
        words = [word for word in re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", title.lower()) if word not in {"pour", "avec", "dans"}]
        return " ".join(words[:4]) or title[:60]

    def _slugify(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        cleaned = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
        return cleaned[:90].strip("-")

    def _canonical_url(self, *, channel: str, locale: str, slug: str) -> str:
        if channel == "mapsi_site":
            return f"https://mapsi.fr/actualites/{slug}"
        prefix = {"fr-FR": "/ressources", "en-US": "/en/resources", "es-ES": "/es/recursos"}.get(locale, "/ressources")
        return f"https://oling.fr{prefix}/{slug}"

    def _localized_image_alt(self, title: str, locale: str) -> str:
        if locale == "en-US":
            return f"Editorial illustration for {title}"
        if locale == "es-ES":
            return f"Ilustracion editorial para {title}"
        return f"Illustration editoriale pour {title}"
