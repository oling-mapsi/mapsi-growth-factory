# Editorial Production V1

Cette V1 ajoute deux builders de production branches sur le moteur editorial reel :

- `MapsiMarketProductionBuilder`
- `OlingPracticeProductionBuilder`

## Generation

MAPSI market :

- charge les `product_changes` des 180 derniers jours ;
- exclut les changements non communicables ;
- selectionne un sujet recent, sinon retombe sur le `feature-catalog` ;
- produit deux articles distincts pour le meme sujet :
  - `mapsi_news_article` pour `mapsi.fr`
  - `oling_news_article` pour `oling.fr`

OLING practice :

- charge les practices versionnees ;
- applique la configuration `config/editorial_practices.yaml` ;
- evite les sujets recents ;
- favorise les practices prioritaires avec contenu suffisant.

## Cycle asset

Chaque asset suit le cycle :

- source selection
- generation
- deterministic validation
- quality evaluation
- draft asset
- `READY_FOR_REVIEW` ou `QUALITY_FAILED`

Les metadonnees editoriales sont conservees dans `results` :

- article structure
- rapport qualite
- execution modele
- contexte builder
- selection du sujet

## Rewrite et regenerate

Les operations admin suivantes sont disponibles :

- `POST /api/admin/v1/editorial/generate-mapsi-market`
- `POST /api/admin/v1/editorial/generate-oling-practice`
- `POST /api/admin/v1/assets/{assetId}/rewrite`
- `POST /api/admin/v1/assets/{assetId}/regenerate`

Chaque reecriture ou regeneration :

- snapshot la version precedente dans `asset_revision_snapshots`
- regenere depuis le `builder_context`
- conserve les sources
- recalcule les hashes
- invalide de fait l'approbation precedente via le changement de contenu
- remet l'asset en `READY_FOR_REVIEW` ou `QUALITY_FAILED`
