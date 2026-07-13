# MGF-409 Real Editorial Engine

## Cause et limite avant correctif

Le moteur editorial etait branche sur une notion unique de `editorial_agent_backend`.
Le pipeline savait produire des sorties structurees, mais il ne distinguait pas clairement :

- le mode d'execution `simulated|real` ;
- le provider reel ou simule ;
- le budget de generation ;
- les metadonnees versionnees de prompt, modele, schema et consommation ;
- les garde-fous explicites contre certaines promesses interdites.

Le resultat etait exploitable pour un pilote, mais pas assez stable pour un moteur remplacable et auditable.

## Correctif

- introduction d'une interface `EditorialProvider` ;
- conservation du provider simule ;
- ajout du provider reel `OpenAIEditorialProvider` via le backend OpenAI existant ;
- propagation des metadonnees d'execution dans les agents ;
- suivi du budget par generation avec `EDITORIAL_GENERATION_MAX_BUDGET_TOKENS` ;
- ajout de `EDITORIAL_ENGINE_MODE=simulated|real` avec fallback simule par defaut ;
- exposition du mode et de la consommation dans les rapports de generation ;
- extension des writers par canal :
  - `ProductChangeAnalyst`
  - `EditorialStrategyAgent`
  - `OlingArticleWriter`
  - `MapsiArticleWriter`
  - `LinkedInPostWriter`
  - `MapsiUserEmailWriter`
  - `ProspectNewsletterWriter`
  - `MapsiStudioContentWriter`
  - `EditorialQualityAgent`
- rejet des sorties qui contiennent :
  - donnees personnelles ;
  - promesse explicite de conformite ;
  - promesse explicite de resultat garanti ;
  - references client non autorisees ;
  - affirmations sans preuves referencees.

## Migrations

Aucune migration SQL dediee n'est ajoutee dans cette PR.
Le correctif reutilise les tables existantes et enrichit les metadonnees deja stockees dans les journaux d'execution.

## Rejeu et fallback

- `EDITORIAL_ENGINE_MODE=simulated` reste le comportement par defaut ;
- `--mode=real` permet de piloter un run de test ;
- si le provider reel n'est pas disponible, l'environnement reste en mode simule tant que la variable n'est pas activee ;
- cette PR n'active pas le mode `real` en production.

## Procedure pilote

1. lancer `mapsi-growth generate-campaign --mode=real --dry-run`
2. comparer le resultat avec le mode `simulated`
3. faire la review humaine dans Studio
4. ne publier aucun contenu automatiquement
5. activer progressivement uniquement apres validation humaine

## Rollback

1. remettre `EDITORIAL_ENGINE_MODE=simulated`
2. redeployer
3. relancer les generations en `--dry-run` pour verification

La logique de publication n'est pas touchee par ce rollback.
