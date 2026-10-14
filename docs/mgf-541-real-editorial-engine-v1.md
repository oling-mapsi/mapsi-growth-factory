# MGF-541 Real Editorial Engine V1

Date: 2026-07-19
Branche: `feature/MGF-541-real-editorial-engine-v1`

## Perimetre

Cette PR ajoute un moteur editorial minimal a agent unique pour produire :

- un article MAPSI destination `mapsi.fr` ;
- un article MAPSI angle conseil destination `oling.fr` ;
- un article OLING practice destination `oling.fr`.

## Architecture

- `EditorialGeneratorInterface`
- `SimulatedEditorialGenerator`
- `OpenAIEditorialGenerator`
- `EditorialQualityValidator`
- `EditorialGenerationService`

Le moteur s'appuie sur le backend OpenAI structure deja present, avec `output_type=EditorialArticle`.

## Commandes

```bash
mapsi-growth editorial:generate-mapsi --destination=mapsi
mapsi-growth editorial:generate-mapsi --destination=oling
mapsi-growth editorial:generate-oling --practice=erp
```

Option utile :

```bash
--mode=simulated|shadow|real
--dry-run
```

## Modes

- `simulated` : generation deterministe locale ;
- `shadow` : generation reelle + enregistrement d'un draft Growth, sans publication ;
- `real` : generation reelle + draft Growth, sans appel direct publisher.

La PR ne bascule aucun fichier versionne en `real`.

## Controles

Validation deterministe apres generation :

- titre, corps, meta, CTA, sources ;
- slug ;
- absence d'email, secret, token ;
- absence de claim non verifiee ;
- HTML dangereux retire ;
- controle de similarite avec historique.

## Persistance

Le draft est stocke dans les tables existantes :

- `campaign_runs`
- `content_assets`
- `source_evidences`
- `agent_execution_logs`

Les metadonnees enregistrees incluent :

- modele ;
- `prompt_version` ;
- `knowledge_version` ;
- `input_hash` ;
- `output_hash` ;
- tokens ;
- cout estime ;
- duree ;
- resultat de validation.
