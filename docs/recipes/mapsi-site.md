# Recette `mapsi_site`

## Portee

La recette couvre le canal `mapsi_site` depuis Growth, sans exposer de secret :

- health ;
- preview ;
- publish ;
- status ;
- replay ;
- kill-switch-test ;
- feature-flag-test ;
- unpublish-test si necessaire.

Le script associe est :

- [scripts/recipe_mapsi_site.sh](/Users/florestanrouet/myweb/mapsi-growth-factory/scripts/recipe_mapsi_site.sh)

## Prerequis

- un jeton Bearer Studio Admin avec les permissions :
  - `GROWTH_VIEW`
  - `GROWTH_REVIEW`
  - `GROWTH_PUBLISH`
  - `GROWTH_CONFIGURE`
  - `GROWTH_AUDIT`
- `curl`
- `jq`
- un fichier d'environnement local protege en `0600`

Exemple minimal de fichier env :

```bash
GROWTH_ADMIN_BEARER_TOKEN=redacted
GROWTH_ADMIN_URL=https://growth.oling.fr
MAPSI_SITE_PUBLIC_BASE_URL=https://www.mapsi.fr
MAPSI_SITE_PUBLIC_LIST_PATH=/actualites
WORKFLOW_KILL_SWITCH_DEFAULT=false
STUDIO_CONFIRMATION_PHRASE=CONFIRM
```

## Asset de recette dedie

Utiliser un asset dedie a la recette, puis le depublicher ou l'archiver a la fin.

- titre : `Test de publication MAPSI Growth`
- slug : `test-publication-mapsi-growth-2026`
- type : `mapsi_news_article`
- canal : `mapsi_site`
- contenu :
  `Article de recette technique destine a verifier le canal de publication Growth vers mapsi.fr.`

Important :

- la recette Studio mentionne parfois `GLOBAL_KILL_SWITCH` ;
- dans Growth, la variable effectivement supportee est `WORKFLOW_KILL_SWITCH`.

## Modes

Mode par defaut :

```bash
scripts/recipe_mapsi_site.sh --env-file /private/path/growth-admin.env
```

Health :

```bash
scripts/recipe_mapsi_site.sh health \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID
```

Preview :

```bash
scripts/recipe_mapsi_site.sh preview \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID
```

Publish reel :

```bash
scripts/recipe_mapsi_site.sh publish \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --confirm-real-publication
```

Replay idempotent :

```bash
scripts/recipe_mapsi_site.sh replay \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --confirm-real-publication
```

Test kill switch avec restauration explicite :

```bash
scripts/recipe_mapsi_site.sh kill-switch-test \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --restore-initial-state
```

Test feature flag avec restauration explicite :

```bash
scripts/recipe_mapsi_site.sh feature-flag-test \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --restore-initial-state
```

## Garanties du script

- mode par defaut `health`
- aucune publication reelle sans `--confirm-real-publication`
- aucun token affiche
- l'etat initial est capture :
  - kill switch global
  - kill switch canal
  - feature flag canal
- un rapport JSON est produit sans donnee sensible
- le script ne desactive jamais silencieusement un kill switch :
  - il ne restaure que si `--restore-initial-state` est fourni
  - sinon il laisse une consigne explicite

## Verifications metier

Avant publication, le script verifie :

- `asset_type == mapsi_news_article`
- `channel == mapsi_site`
- asset approuve
- `content_hash == approved_content_hash`
- readiness `ready`
- cible publique `mapsi_web` saine

En mode `preview`, il verifie aussi que le titre n'apparait pas deja dans la liste publique.

En mode `replay`, il verifie :

- meme `external_publication_id`
- meme `public_url`
- `idempotent_replay=true` dans le rapport

## Limites connues

- l'etat initial du kill switch global est deduit via l'audit si disponible ; sinon le script retombe sur `WORKFLOW_KILL_SWITCH_DEFAULT` depuis le fichier env local.
- `unpublish-test` modifie l'etat public ; il doit etre utilise avec prudence.

## Checklist manuelle Studio

1. Ouvrir l'asset `mapsi_news_article` dans Studio.
2. Verifier :
   - statut `APPROVED`
   - empreinte approuvee conforme
   - preview disponible
3. Lancer `create-preview` et confirmer que l'article n'apparait pas sur la liste publique `mapsi_web`.
4. Lancer `publish`.
5. Verifier dans Studio :
   - `publisher = mapsi_site_api` ou `mapsi_site_mock`
   - `publication_status = PUBLISHED`
   - `external_publication_id` renseigne
   - `public_url` renseignee
6. Relancer `publish` avec la meme requete de rejeu outillee.
7. Verifier qu'aucun nouvel article n'est cree.
8. Tester ensuite :
   - kill switch canal
   - feature flag canal
9. Si `unpublish-test` est execute, verifier ensuite la restoration attendue manuellement.

## Recette reelle Studio -> Growth -> mapsi_web

### Test 1 - Preview sans publication

Dans Studio :

1. creer ou selectionner une campagne de test ;
2. generer l'asset `mapsi_news_article` dedie ;
3. verifier le contenu ;
4. approuver l'asset ;
5. creer la preview ;
6. ouvrir l'URL de preview ;
7. verifier que l'article n'apparait pas dans `/actualites` ;
8. verifier qu'il n'est pas accessible sans token.

Commande de controle :

```bash
scripts/recipe_mapsi_site.sh preview \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID
```

### Test 2 - Feature flag desactive

Etat attendu :

- `PUBLISH_MAPSI_SITE_ENABLED=false`

Puis tenter la publication depuis Studio ou via le script.

Resultat attendu :

- publication refusee ;
- aucune modification distante ;
- audit enregistre ;
- asset toujours `APPROVED`.

Commande :

```bash
scripts/recipe_mapsi_site.sh feature-flag-test \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --restore-initial-state
```

### Test 3 - Kill switch actif

Etat attendu :

- `PUBLISH_MAPSI_SITE_ENABLED=true`
- `WORKFLOW_KILL_SWITCH=true`

Resultat attendu :

- publication refusee ;
- aucun nouvel article public ;
- raison explicite dans Studio ;
- audit enregistre.

Commande :

```bash
scripts/recipe_mapsi_site.sh kill-switch-test \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --restore-initial-state
```

### Test 4 - Publication reelle

Etat temporaire requis :

- `PUBLISH_MAPSI_SITE_ENABLED=true`
- `WORKFLOW_KILL_SWITCH=false`

Puis :

1. publier depuis Studio ;
2. relire l'etat dans Growth ;
3. ouvrir l'URL publique ;
4. verifier `/actualites` ;
5. verifier la page detail ;
6. verifier les metadonnees ;
7. verifier le back-office `mapsi_web` ;
8. verifier l'audit.

Commande :

```bash
scripts/recipe_mapsi_site.sh publish \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --confirm-real-publication
```

### Test 5 - Idempotence

Relancer exactement la meme publication.

Resultat attendu :

- meme identifiant distant ;
- meme URL ;
- aucun nouvel article ;
- aucun nouveau slug ;
- statut `PUBLISHED` ;
- resultat marque idempotent ou deja publie.

Commande :

```bash
scripts/recipe_mapsi_site.sh replay \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID \
  --confirm-real-publication
```

### Test 6 - Mise a jour

Dans Studio :

1. modifier l'asset ;
2. verifier que l'approbation precedente est invalidee ;
3. verifier qu'une nouvelle version est creee ;
4. reapprouver ;
5. republier.

Resultat attendu :

- mise a jour de l'article distant existant ;
- aucun second article cree.

### Test 7 - Unpublish

Seulement si le backend distant le supporte reellement.

Resultat attendu :

- article retire de la liste publique ;
- page inaccessible ou marquee non publiee ;
- statut Growth synchronise ;
- audit present.

Commande :

```bash
scripts/recipe_mapsi_site.sh unpublish-test \
  --growth-url https://growth.oling.fr \
  --env-file /private/path/growth-admin.env \
  --asset-id ASSET_ID
```

### Retour obligatoire a l'etat sur

En fin de recette, remettre imperativement :

- `PUBLISH_MAPSI_SITE_ENABLED=false`
- `WORKFLOW_KILL_SWITCH=true`
