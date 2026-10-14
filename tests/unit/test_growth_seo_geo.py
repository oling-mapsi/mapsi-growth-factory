from app.application.services.growth_seo_geo import GrowthSeoGeoService


def test_oling_seo_geo_uses_article_canonical_and_localized_slug(monkeypatch) -> None:
    service = GrowthSeoGeoService()
    monkeypatch.setattr(service, "_verified_links", lambda links: [{**links[0], "final_url": links[0]["url"], "status_code": 200}])

    result = service.prepare(
        channel="oling_site",
        locale="es-ES",
        title="Coordinación projet : réduire les relances",
        html="<h2>Uno</h2><p>Texto</p>",
        text="Texto largo sobre metodo, etapas y puntos de control " * 30,
    )

    assert result.metadata["slug"] == "coordinacion-projet-reduire-les-relances"
    assert result.metadata["canonical"] == "https://oling.fr/es/recursos/coordinacion-projet-reduire-les-relances"
    assert result.metadata["canonical"] != "https://oling.fr/"
    assert "También puede leer" in result.html
    assert result.metadata["locale"] == "es-ES"


def test_mapsi_seo_geo_stays_french_article_url(monkeypatch) -> None:
    service = GrowthSeoGeoService()
    monkeypatch.setattr(service, "_verified_links", lambda links: [{**links[0], "final_url": links[0]["url"], "status_code": 200}])

    result = service.prepare(
        channel="mapsi_site",
        locale="fr-FR",
        title="Traçabilité QHSE améliorée",
        html="<h2>Un</h2><p>Texte</p>",
        text="Texte long sur la methode, les etapes et les points de controle " * 30,
    )

    assert result.metadata["canonical"] == "https://mapsi.fr/fr/actualites/tracabilite-qhse-amelioree"
    assert result.metadata["locale"] == "fr-FR"
