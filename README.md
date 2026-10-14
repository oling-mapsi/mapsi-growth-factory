# MAPSI Growth Factory

Socle technique FastAPI pour orchestrer des campagnes marketing en architecture hexagonale, sans connexion réelle aux systèmes externes.

## Architecture

```text
app/
  domain/          # Entités, états, règles métier
  application/     # Cas d’usage, DTO, ports
  infrastructure/  # SQLAlchemy, connecteurs simulés, audit
  entrypoints/     # API FastAPI
  core/            # Config, sécurité, base de données
```

## Workflow Codex

Les regles de travail cross-repository sont formalisees dans [AGENTS.md](/Users/florestanrouet/myweb/mapsi-growth-factory/AGENTS.md) et [docs/cross-repository-workflow.md](/Users/florestanrouet/myweb/mapsi-growth-factory/docs/cross-repository-workflow.md).

Une evolution qui touche `mapsi-v6` et `mapsi-growth-factory` doit produire deux taches Codex et deux pull requests.
La PR Growth Factory ne se fusionne qu'apres la PR MAPSI, sauf si Growth reste branche sur un simulateur.

Le manifeste des labels GitHub a appliquer dans les deux depots est fourni dans [.github/labels.yml](/Users/florestanrouet/myweb/mapsi-growth-factory/.github/labels.yml).

Une config Codex locale conservative est ajoutee dans [.codex/config.toml](/Users/florestanrouet/myweb/mapsi-growth-factory/.codex/config.toml) avec un exemple de branchement futur d'un MCP GitHub officiel en lecture seule.

## Prérequis

- Python 3.12
- Docker et Docker Compose

## Installation locale

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
alembic upgrade head
uvicorn app.main:app --reload
```

## Lancer avec Docker

```bash
cp .env.example .env
docker compose up --build
```

## Tests

```bash
pytest
```

## Contrat MAPSI versionne

Le contrat consomme par Growth Factory est stocke dans [contracts/mapsi](/Users/florestanrouet/myweb/mapsi-growth-factory/contracts/mapsi) et ne depend pas du depot local `mapsi-v6`.

Commandes :

```bash
make contracts-sync MAPSI_REF_TYPE=tag MAPSI_REF=v1.2.0
make contracts-check
make mapsi-mock
```

Le processus detaille est documente dans [docs/mapsi-contract-update.md](/Users/florestanrouet/myweb/mapsi-growth-factory/docs/mapsi-contract-update.md).

## Tests d'integration PostgreSQL

```bash
docker compose --profile test up -d postgres_test redis
TEST_DATABASE_URL=postgresql+psycopg://mapsi:mapsi@localhost:5433/mapsi_growth_factory_test pytest -m postgres
```

## Worker Redis

```bash
python -m app.worker
```

Le worker consomme la file Redis et exécute les jobs applicatifs.

## GitHub Product Intelligence

Webhook :

```text
POST /webhooks/github
```

Contraintes :

- verification de `X-Hub-Signature-256`
- livraison GitHub idempotente via `X-GitHub-Delivery`
- depot refuse s'il n'est pas dans `GITHUB_ALLOWED_REPOSITORIES`
- aucun jeton personnel
- GitHub App uniquement avec jeton d'installation court

Fallback hebdomadaire :

```bash
python3 scripts/run_github_weekly_backfill.py
```

## Collecteur d'usage MAPSI

Configuration multi-instance :

```yaml
instances:
  - id: gpmlm
    base_url: https://mapsi-client-1.example
    secret_ref: vault://mapsi/gpmlm/growth-token
    enabled: true
```

Les secrets ne sont jamais commites. Ils sont resolus via variables d'environnement au format :

```text
SECRET__MAPSI__GPMLM__GROWTH_TOKEN=...
```

Commande :

```bash
mapsi-growth collect-mapsi-usage --instance=gpmlm --dry-run
```

Le rapport de collecte ne contient aucune donnee personnelle et resume :

- instances reussies
- instances en erreur
- utilisateurs actifs
- utilisateurs eligibles
- exclusions
- duree

## Segmentation d'audience

Les segments deterministes versionnes sont stockes dans [config/audience-segments](/Users/florestanrouet/myweb/mapsi-growth-factory/config/audience-segments).
Aucun agent ne peut fournir de SQL libre : il peut seulement choisir un segment existant ou proposer une regle desactivee conforme au schema JSON.

Commande de previsualisation :

```bash
mapsi-growth preview-audience-segment --segment=all_eligible_active_users --dry-run
```

Pour tester une proposition non activee :

```bash
mapsi-growth preview-audience-segment --rule-file=/tmp/proposed-segment.json --dry-run
```

La previsualisation retourne uniquement des agregats : volume total, volume eligible, exclusions par motif, repartitions par role/module/client et raisons de blocage.

## Synchronisation Mautic

Variables d'environnement principales :

- `MAUTIC_BASE_URL`
- `MAUTIC_USERNAME` et `MAUTIC_PASSWORD`, ou `MAUTIC_ACCESS_TOKEN`
- `MAUTIC_VERIFY_TLS`
- `CONTACT_ENCRYPTION_KEY`

Provisioning idempotent :

```bash
python3 scripts/provision_mautic.py
mapsi-growth provision-mautic --dry-run
```

Synchronisation des contacts eligibles vers Mautic :

```bash
mapsi-growth sync-mautic-contacts --dry-run
```

Contraintes :

- aucun email envoye dans cette PR ;
- aucun email en clair dans les rapports ;
- les oppositions, desabonnements, emails invalides et utilisateurs desactives sont exclus ou mis DNC ;
- un contact deja DNC n'est jamais reactive automatiquement ;
- les emails presents dans plusieurs instances sont fusionnes dans un seul contact Mautic avec agrgation des roles, modules, instances et clients.

Sandbox local :

```bash
make mautic-mock
```

Publication Mautic approuvee :

- preview : `POST /ops/campaigns/{id}/mautic-preview`
- planification : `POST /ops/campaigns/{id}/mautic-schedule`

Contraintes :

- seulement apres approbation explicite ;
- idempotence par campagne/version ;
- aucun second envoi de la meme version ;
- verification DNC juste avant planification ;
- arret d'urgence global via `WORKFLOW_KILL_SWITCH` ;
- arret par instance/client via `PUBLICATION_INSTANCE_KILL_SWITCHES` et `PUBLICATION_CLIENT_KILL_SWITCHES` ;
- en local, brancher Mautic sur Mailpit via `MAILPIT_BASE_URL`.

## Publication LinkedIn

Services :

- `LinkedInOAuthService`
- `LinkedInOrganizationResolver`
- `LinkedInPostPublisher`
- `LinkedInMediaUploader`
- `LinkedInMetricsCollector`

Variables d'environnement principales :

- `LINKEDIN_MODE=mock` par defaut tant que les droits officiels ne sont pas accordes
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REDIRECT_URI`
- `LINKEDIN_COMPANY_ID=3347696`
- `LINKEDIN_ORGANIZATION_URN` optionnel si l'URN est deja connue
- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_REFRESH_TOKEN`

Endpoints internes :

- `GET /ops/linkedin/oauth/authorization-url`
- `POST /ops/linkedin/oauth/exchange`
- `POST /ops/campaigns/{id}/linkedin-publish`
- `POST /ops/campaigns/{id}/linkedin-metrics`

Contraintes :

- API officielles LinkedIn uniquement ;
- aucun scraping ;
- aucune automatisation navigateur ;
- publication interdite si l'asset LinkedIn n'est pas `APPROVED` ;
- idempotence par `content_hash` et `Idempotency-Key` ;
- journalisation sans jeton ;
- gestion du renouvellement de jeton et de l'expiration ;
- collecte de statistiques de post ;
- le type `linkedin_personal_draft` reste en mode copie manuelle et ne publie rien via API.

## Mesure de l'adoption

Endpoints internes :

- `POST /ops/campaigns/{id}/collect-adoption-metrics`
- `GET /ops/campaigns/{id}/adoption-report`
- `GET /ops/reports/adoption-weekly`

Garanties :

- import des evenements Mautic `sent`, `delivered`, `opened`, `clicked`, `bounced`, `unsubscribed`, `complaint` ;
- stockage uniquement pseudonymise dans `interactions` ;
- aucune route n'expose les evenements nominatifs ;
- comparaison usage avant campagne, apres 7 jours, apres 30 jours ;
- alertes sur desabonnements, rebonds, delivrabilite, absence d'effet et hausse d'erreurs.

Limites d'attribution :

- les deltas d'usage restent correlatifs ;
- une hausse ou baisse peut aussi venir d'autres actions produit, support ou contexte client.

## Agents editoriaux lot 1

Prompts versionnes :

- [prompts/product-intelligence-agent/v1.txt](/Users/florestanrouet/myweb/mapsi-growth-factory/prompts/product-intelligence-agent/v1.txt)
- [prompts/usage-intelligence-agent/v1.txt](/Users/florestanrouet/myweb/mapsi-growth-factory/prompts/usage-intelligence-agent/v1.txt)
- [prompts/editorial-strategy-agent/v1.txt](/Users/florestanrouet/myweb/mapsi-growth-factory/prompts/editorial-strategy-agent/v1.txt)
- [prompts/customer-email-writer-agent/v1.txt](/Users/florestanrouet/myweb/mapsi-growth-factory/prompts/customer-email-writer-agent/v1.txt)
- [prompts/quality-control-agent/v1.txt](/Users/florestanrouet/myweb/mapsi-growth-factory/prompts/quality-control-agent/v1.txt)

Backends :

- `EDITORIAL_AGENT_BACKEND=simulated` pour les tests et le local
- `EDITORIAL_AGENT_BACKEND=openai` pour utiliser l'adaptateur OpenAI Agents SDK si le package `agents` est installe

Commande :

```bash
mapsi-growth generate-weekly-campaign --dry-run
```

Garanties :

- aucune adresse email, aucun nom utilisateur, aucun secret ni identifiant de contact n'est transmis aux modeles ;
- toute affirmation doit referencer des `source_evidence_id` valides ;
- un theme recent est bloque ;
- un segment non active est bloque ;
- un echec du controle qualite bloque la campagne.

## Lot 2 : modele multicanal

Types d'assets ajoutes :

- `customer_email`
- `prospect_newsletter`
- `linkedin_company_post`
- `linkedin_personal_draft`
- `website_article`
- `website_cta`
- `demonstration_landing_page`

Chaque asset persiste :

- contenu propre ;
- `evidence_ids` ;
- `audience_segment_id` ;
- `status` ;
- `content_hash` ;
- approbation asset (`approved_by`, `approved_at`) ;
- planification (`scheduled_at`) ;
- `results`.

Commande :

```bash
mapsi-growth generate-market-assets --campaign-id=<campaign_id> --dry-run
```

Contraintes lot 2 :

- aucune publication automatique ;
- toute affirmation doit rester liee a une preuve ;
- aucun client cite sans autorisation explicite ;
- aucun retour d'experience invente ;
- distinction entre benefice demontre et benefice attendu.

## Portail provisoire de validation

Interface HTML minimale :

- `GET /review/{token}`
- edition du contenu ;
- demande de nouvelle version ;
- approbation ;
- rejet ;
- revocation du jeton.

Securite :

- authentification admin Basic via `REVIEW_ADMIN_USERNAME` et `REVIEW_ADMIN_PASSWORD` ;
- jetons expirables, a usages limites et revocables ;
- aucune liste complete d'emails n'est affichee ;
- a l'approbation, `approved_content_hash` et `approved_audience_hash` sont enregistres ;
- toute publication est refusee si le contenu ou l'audience differe apres approbation.

## Idempotence API

Toutes les routes `POST /campaigns*` acceptent l’en-tête `Idempotency-Key`.
Une même clé avec le même payload rejoue la même réponse.
Une même clé avec un payload différent retourne `409 Conflict`.

Les routes d'orchestration `POST /ops/*` utilisent la meme cle d'idempotence pour n8n.

## Authentification

Toutes les routes `/campaigns` exigent l’en-tête `X-API-Key`, utilisé pour l’authentification MAPSI -> API.
Les routes `/ops` exigent le meme en-tete.

## Workflows n8n

Les exports importables sont dans [n8n/workflows](/Users/florestanrouet/myweb/mapsi-growth-factory/n8n/workflows).

Validation locale :

```bash
python3 scripts/validate_n8n_workflows.py
```

Documentation :

- [docs/n8n-import.md](/Users/florestanrouet/myweb/mapsi-growth-factory/docs/n8n-import.md)
- [n8n/credentials.example/README.md](/Users/florestanrouet/myweb/mapsi-growth-factory/n8n/credentials.example/README.md)

## Flux métier couvert

1. Création d’une campagne en `DRAFT`.
2. Génération des contenus et preuves simulées en `GENERATED`.
3. Demande de changements avec incrément de révision des assets.
4. Approbation autorisée seulement si des assets et des sources existent.
5. Publication multi-canaux autorisée uniquement depuis `APPROVED`, puis idempotente sur un canal déjà publié.

## Migrations

```bash
alembic upgrade head
```

## Limites de cette première PR

- Connecteurs externes simulés uniquement.
- Les workers asynchrones consommant Redis restent à brancher côté runtime.
- Les tests PostgreSQL nécessitent Docker disponible sur la machine d’exécution.
