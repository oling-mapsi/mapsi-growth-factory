# Oling Real Publisher

Date: 2026-07-12
Branche: `feature/MGF-202-oling-real-publisher`

## Contrat externe utilise

Contrat lu dans le depot local `../olingw` :

- `../olingw/docs/growth-publishing-api.md`
- `../olingw/src/Controller/GrowthPublishingController.php`
- `../olingw/src/Service/GrowthPublishingService.php`
- `../olingw/src/Dto/GrowthNewsInput.php`
- `../olingw/src/Service/GrowthApiAuthenticator.php`

Endpoints reels cibles :

- `POST /api/growth/news`
- `PATCH /api/growth/news/{externalId}`
- `POST /api/growth/news/{externalId}/preview-url`
- `POST /api/growth/news/{externalId}/publish`
- `GET /api/growth/news/{externalId}`
- `POST /api/growth/news/{externalId}/unpublish`

## Modes supportes

- `OLING_MODE=mock`
  - utilise `OlingMockPublisher`
  - mode recommande pour local et CI
- `OLING_MODE=preview-only`
  - utilise l'API reelle pour brouillon + preview
  - bloque la publication publique
- `OLING_MODE=live`
  - utilise l'API reelle et autorise `publish`
  - reste bloque tant que `PUBLISH_OLING_ENABLED=false`

## Variables d'environnement

- `PUBLISH_OLING_ENABLED=false`
- `OLING_MODE=mock`
- `OLING_BASE_URL=https://www.oling.fr`
- `OLING_SITE_BASE_URL=https://www.oling.fr`
- `OLING_API_TOKEN=...`
- `OLING_VERIFY_TLS=true`
- `OLING_TIMEOUT_SECONDS=10`
- `OLING_MAX_RETRIES=2`
- `OLING_RETRY_BACKOFF_SECONDS=0.25`
- `OLING_CIRCUIT_BREAKER_THRESHOLD=3`
- `OLING_CIRCUIT_BREAKER_RESET_SECONDS=60`
- `WORKFLOW_KILL_SWITCH`

## Garde-fous

La publication Oling est refusee si :

- l'asset n'est pas `APPROVED`
- `content_hash != approved_content_hash`
- `PUBLISH_OLING_ENABLED=false`
- `WORKFLOW_KILL_SWITCH=true`
- le controle qualite du review bundle est marque en echec
- le titre ou le contenu sont absents
- l'authentification distante est invalide
- `OLING_MODE=preview-only`

## Donnees persistantes

Table ajoutee :

- `oling_news_publications`

Donnees stockees :

- `external_id`
- `content_hash`
- `preview_url`
- `public_url`
- `public_slug`
- `draft_revision_number`
- `published_revision_number`
- `published_content_version`
- `published_at`
- `unpublished_at`
- `status`
- `last_error`
- `metrics`

En parallele, l'asset met aussi a jour :

- `external_publication_id`
- `external_publication_url`
- `published_at`
- `results.preview_url`
- `results.public_url`

## Commande CLI

```bash
mapsi-growth publish-asset --asset-id=<asset_id> --channel=oling --dry-run
```

Effet :

- `--dry-run` cree ou met a jour le brouillon puis recupere une preview ;
- sans `--dry-run`, la commande tente la publication via `OlingNewsPublisher`.

## Deploiement recommande

1. deployer le code
2. executer `alembic upgrade head`
3. laisser `PUBLISH_OLING_ENABLED=false`
4. valider d'abord avec `OLING_MODE=mock` ou `OLING_MODE=preview-only`
5. verifier la commande CLI `publish-asset --dry-run`
6. basculer eventuellement `OLING_MODE=live`
7. n'activer `PUBLISH_OLING_ENABLED=true` qu'apres validation complete

## Retour arriere

1. remettre `PUBLISH_OLING_ENABLED=false`
2. remettre `OLING_MODE=mock`
3. redeployer le commit precedent si necessaire
4. executer `alembic downgrade 20260711_0012`

Le rollback SQL supprime uniquement `oling_news_publications`. Les champs asset generiques ajoutes en `MGF-201` restent inchanges.
