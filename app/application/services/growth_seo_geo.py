from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class GrowthSeoGeoResult:
    status: str
    checks: list[dict]
    metadata: dict
    internal_links: list[dict]
    html: str


class GrowthSeoGeoService:
    OILING_LINKS = [
        {"label": "OLING", "url": "https://oling.fr/"},
        {"label": "Ressources OLING", "url": "https://oling.fr/ressources"},
        {"label": "AMOA SI", "url": "https://oling.fr/amoa-si"},
        {"label": "Contact OLING", "url": "https://oling.fr/contact"},
    ]
    MAPSI_LINKS = [
        {"label": "MAPSI", "url": "https://mapsi.fr/"},
        {"label": "MAPSI logiciel QHSE", "url": "https://mapsi.fr/fr/"},
    ]

    def prepare(self, *, channel: str, title: str, html: str, text: str, image_alt: str = "") -> GrowthSeoGeoResult:
        links = self._verified_links(self.MAPSI_LINKS if channel == "mapsi_site" else self.OILING_LINKS)
        enriched_html = self._insert_links(html, links)
        metadata = {
            "h1": title,
            "seo_title": title[:70],
            "meta_description": self._summary(text, 155),
            "slug": self._slugify(title),
            "canonical": links[0]["url"] if links else "",
            "primary_keyword": self._primary_keyword(title),
            "summary": self._summary(text, 260),
            "image_alt": image_alt,
            "open_graph": {"title": title[:70], "description": self._summary(text, 155)},
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": title[:110],
                "description": self._summary(text, 155),
            },
        }
        checks = self._checks(title=title, html=enriched_html, text=text, metadata=metadata, links=links, image_alt=image_alt)
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
        if not links or "A lire aussi" in html:
            return html
        items = "".join(f'<li><a href="{link["final_url"]}">{link["label"]}</a></li>' for link in links[:3])
        return html.rstrip() + f"<h2>A lire aussi</h2><ul>{items}</ul>"

    def _checks(self, *, title: str, html: str, text: str, metadata: dict, links: list[dict], image_alt: str) -> list[dict]:
        return [
            {"code": "title", "label": "Titre editorial", "passed": bool(title.strip()), "severity": "error"},
            {"code": "meta_description", "label": "Meta description", "passed": len(metadata["meta_description"]) >= 80, "severity": "error"},
            {"code": "slug", "label": "Slug lisible", "passed": bool(metadata["slug"]), "severity": "error"},
            {"code": "structure", "label": "Structure H2", "passed": html.count("<h2") >= 2, "severity": "warning"},
            {"code": "internal_links", "label": "Liens internes verifies", "passed": len(links) >= 1, "severity": "error"},
            {"code": "image_alt", "label": "Texte alternatif image", "passed": bool(image_alt.strip()), "severity": "warning"},
            {"code": "json_ld", "label": "Donnees structurees Article", "passed": metadata["json_ld"]["headline"] != "", "severity": "error"},
            {"code": "geo", "label": "Passages structurables IA", "passed": len(text) >= 900 and bool(re.search(r"\\b(comment|pourquoi|methode|points?|etapes?)\\b", text, re.I)), "severity": "warning"},
            {"code": "canonical", "label": "Canonical valide", "passed": urlparse(metadata["canonical"]).scheme == "https", "severity": "error"},
        ]

    def _summary(self, text: str, limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:limit].rstrip()

    def _primary_keyword(self, title: str) -> str:
        words = [word for word in re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", title.lower()) if word not in {"pour", "avec", "dans"}]
        return " ".join(words[:4]) or title[:60]

    def _slugify(self, value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return cleaned[:90].strip("-")
