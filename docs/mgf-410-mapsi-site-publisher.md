# MGF-410 Mapsi Site Publisher

## Portee

Ajout d'un publisher `mapsi_site` avec :

- preview ;
- publication ;
- statut ;
- idempotence par `content_hash` ;
- respect du feature flag `PUBLISH_MAPSI_SITE_ENABLED` ;
- respect des kill switches operationnels ;
- affichage dans MAPSI Studio.

## Composants

- `MapsiNewsPublisher`
- `MapsiSiteConnector`
- `contracts/mapsi_site/openapi.yaml`
- `app/mock_mapsi_site_server.py`
- `MapsiNewsPublicationRepository`
- table `mapsi_news_publications`

## Configuration

- `MAPSI_SITE_MODE=mock|preview-only|live`
- `MAPSI_SITE_BASE_URL`
- `MAPSI_SITE_PUBLIC_BASE_URL`
- `MAPSI_SITE_API_TOKEN`
- `PUBLISH_MAPSI_SITE_ENABLED`

## Comportement

- un second publish sur le meme `asset_id` + `content_hash` ne republie rien ;
- le resultat publie existant est retourne ;
- `external_publication_id` correspond desormais a `article_id` distant, distinct du `growth_external_id` ;
- `idempotent_replay`, `correlation_id`, `remote_status`, `remote_version` et `preview_url` sont persistés dans le resultat local ;
- le client valide les reponses `draft`, `preview`, `publish`, `status` et `unpublish` contre le contrat reel ;
- `publish` en timeout relit le statut distant avant tout nouvel essai ;
- `unpublish` n'est considere supporte que si le contrat local le declare et si l'API distante ne repond pas `UNPUBLISH_NOT_SUPPORTED` ;
- le statut et les URLs sont persistés sur l'asset et dans le stockage de publication ;
- Studio expose preview, publish, retry, cancel, unpublish et publication-status pour `mapsi_site`.

## Commandes

- `mapsi-growth mapsi-site:diagnose`
- `mapsi-growth mapsi-site:recipe --asset-id=<asset_id> --mode=preview`
- `mapsi-growth mapsi-site:recipe --asset-id=<asset_id> --mode=publish`

Les rapports n'exposent aucun secret.

## Migration

- `alembic/versions/20260712_0018_mapsi_site_publisher.py`

## Rollback

1. remettre `PUBLISH_MAPSI_SITE_ENABLED=false`
2. redeployer
3. si necessaire, rollback schema via l'outil de migrations
