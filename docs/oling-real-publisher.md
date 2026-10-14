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

## MGF-401 - Cohérence d'état de publication

Cause :
- le statut publie etait persiste cote `oling_news_publications`, mais pas resynchronise de facon fiable sur l'asset et la campagne lors d'un `publish-asset` direct ;
- `mode` restait celui du draft initial, meme apres une publication reelle reussie ;
- le rejeu idempotent retournait un resultat partiel sans revalider l'etat metier publie.

Correctif :
- ajout des champs persistés `publication_mode_requested`, `publication_mode_executed`, `publisher_type`, `publication_status` ;
- synchronisation metier asset/campagne/publication apres succes, rejeu et reconciliation apres erreur reseau ;
- commande CLI `diagnose-asset` pour inspecter l'etat Oling complet d'un asset.

Migration :
- alembic `20260712_0014_oling_publication_state_consistency` ajoute les nouveaux champs et backfill les lignes existantes.

Comportement apres rejeu :
- si la meme version de contenu est deja publiee, aucun second publish distant n'est emis ;
- le resultat publie existant est renvoye avec le meme identifiant externe, la meme URL et la meme cle d'idempotence persistée.

Rollback :
- revenir au code precedent ;
- executer le downgrade Alembic `20260712_0013` pour retirer les nouveaux champs si necessaire ;
- les anciennes colonnes `status` et `mode` restent conservees pendant cette PR pour limiter le risque de retour arriere.
6. basculer eventuellement `OLING_MODE=live`
7. n'activer `PUBLISH_OLING_ENABLED=true` qu'apres validation complete

## Retour arriere

1. remettre `PUBLISH_OLING_ENABLED=false`
2. remettre `OLING_MODE=mock`
3. redeployer le commit precedent si necessaire
4. executer `alembic downgrade 20260711_0012`

Le rollback SQL supprime uniquement `oling_news_publications`. Les champs asset generiques ajoutes en `MGF-201` restent inchanges.
