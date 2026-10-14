from app.application.services.growth_seo_geo import GrowthSeoGeoService


def test_oling_seo_geo_uses_article_canonical_and_localized_slug(monkeypatch) -> None:
    class Catalog:
        def candidates(self, **kwargs):
            assert kwargs['locale'] == 'es-ES'
            return [{'label':'Coordinacion', 'url':'https://oling.fr/es/servicios/coordinacion', 'anchor':'Texto', 'verification':'verified'}]
    service = GrowthSeoGeoService(catalog=Catalog())

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
    assert '<a href="https://oling.fr/es/servicios/coordinacion">Texto</a>' in result.html
    assert 'Read also' not in result.html
    assert result.metadata["locale"] == "es-ES"


def test_mapsi_seo_geo_stays_french_article_url(monkeypatch) -> None:
    class Catalog:
        def candidates(self, **kwargs):
            return []
    service = GrowthSeoGeoService(catalog=Catalog())

    result = service.prepare(
        channel="mapsi_site",
        locale="fr-FR",
        title="Traçabilité QHSE améliorée",
        html="<h2>Un</h2><p>Texte</p>",
        text="Texte long sur la methode, les etapes et les points de controle " * 30,
    )

    assert result.metadata["canonical"] == "https://mapsi.fr/actualites/tracabilite-qhse-amelioree"
    assert result.metadata["locale"] == "fr-FR"
