# MGF-201 Multichannel Assets Migration

Date: 2026-07-11
Branche: `feature/MGF-201-multichannel-assets`

## Perimetre

Cette PR adapte le modele existant dans :

- `app/domain/entities.py`
- `app/domain/enums.py`
- `app/application/ports/connectors.py`
- `app/application/services/campaign_service.py`
- `app/application/services/linkedin_post_publisher.py`
- `app/application/services/multichannel_content_service.py`
- `app/infrastructure/connectors/fakes.py`
- `app/infrastructure/db/models.py`
- `app/infrastructure/repositories/campaigns.py`
- `app/entrypoints/api/dependencies.py`
- `app/entrypoints/api/schemas.py`
- `alembic/versions/20260711_0012_multichannel_assets_model.py`

Aucun connecteur reel supplementaire n'est branche dans cette PR. Les implementations sandbox restent actives.

## Changement de modele

Le modele `ContentAsset` est etendu, pas remplace.

Nouveaux champs persistants dans `content_assets` :

- `locale`
- `subject`
- `content_html`
- `content_text`
- `excerpt`
- `call_to_action`
- `target_url`
- `source_evidence_ids`
- `content_version`
- `approved_content_hash`
- `published_at`
- `external_publication_id`
- `external_publication_url`
- `last_error`
- `retry_count`

Nouveaux champs persistants dans `publications` :

- `content_asset_id`
- `external_url`

Evolution d'etat :

- `CampaignStatus.PARTIALLY_PUBLISHED`
- statuts asset etendus dans `app/domain/enums.py`

## Compatibilite historique

La compatibilite est preservee de trois manieres :

1. `ContentAsset` conserve les champs historiques `body`, `evidence_ids` et `revision` dans `app/domain/entities.py`.
2. `SqlAlchemyCampaignRepository` synchronise ancien et nouveau modele dans `app/infrastructure/repositories/campaigns.py`.
3. la migration `20260711_0012` backfill les donnees historiques.

Backfills executes par la migration :

- `content_html <- body`
- `content_text <- body`
- `subject <- title` pour `channel = 'mautic'`
- `source_evidence_ids <- evidence_ids`
- `content_version <- revision`
- `approved_content_hash <- content_hash` pour les assets deja approuves

Consequence attendue :

- les campagnes historiques restent lisibles sans regeneration ;
- le pipeline existant continue a fonctionner avec les assets deja produits ;
- les publishers simules continuent a recevoir des assets compatibles.

## Feature flags

Ajoutes dans `app/core/config.py`, tous a `False` par defaut :

- `publish_oling_enabled`
- `publish_mapsi_site_enabled`
- `publish_linkedin_enabled`
- `send_mapsi_users_enabled`
- `send_prospect_newsletter_enabled`
- `publish_mapsi_studio_enabled`

Cette PR ne bascule aucun flux vers un systeme externe reel.

## Ordre de deploiement recommande

1. deployer le code ;
2. executer la migration `alembic upgrade head` ;
3. verifier qu'aucun flag de publication reel n'est active ;
4. executer la suite de tests ;
5. verifier la lecture d'une campagne historique et d'une nouvelle campagne generee.

## Controle post-migration

Verifier au minimum :

- une campagne historique expose encore ses assets via l'API ;
- une nouvelle campagne peut etre generee, approuvee et publiee via simulateurs ;
- un asset modifie apres approbation repasse uniquement lui-meme en `READY_FOR_REVIEW` ;
- une campagne peut finir en `PARTIALLY_PUBLISHED`.

## Retour arriere

Si le rollback applicatif est necessaire avant activation de connecteurs reels :

1. arreter les publications en cours ;
2. redeployer le commit precedent ;
3. executer `alembic downgrade 20260711_0011` ;
4. verifier que les routes `/campaigns` et `/ops/*` repondent de nouveau avec le schema precedent.

Limite du rollback :

- les colonnes ajoutees par `20260711_0012` sont supprimees au downgrade ;
- les metadonnees uniquement stockees dans ces nouvelles colonnes seront perdues ;
- les champs historiques `body`, `evidence_ids` et `revision` restent la base de repli.

## Risques connus

- la route de publication generique devient asset-centric : publier un canal sans asset approuve associe est maintenant refuse ;
- `linkedin_post_publisher` doit rester idempotent apres premier publish, ce qui est couvert par `tests/unit/test_linkedin_services.py` ;
- la migration remplit `content_text` depuis `body` sans normalisation riche HTML, ce qui reste acceptable pour la compatibilite mais devra etre surveille si un editeur riche est introduit plus tard.
