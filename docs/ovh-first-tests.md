# OVH first tests

Objectif: demarrer une stack minimale sur le VPS OVH pour tester l'API, PostgreSQL, Redis et le worker, sans exposition publique initiale.

## Principe

- `api` ecoute sur `127.0.0.1:8000` sur le VPS
- acces depuis le poste local via tunnel SSH
- `WORKFLOW_KILL_SWITCH=true` par defaut
- `EDITORIAL_AGENT_BACKEND=simulated`
- `LINKEDIN_MODE=mock`

## Fichiers utilises

- `docker-compose.ovh.yml`
- `deploy/ovh.env.example`

## Demarrage

1. Copier `deploy/ovh.env.example` vers `.env` sur le serveur.
2. Changer au minimum:
   - `MAPSI_API_KEY`
   - `CONTACT_HASH_SALT`
   - `CONTACT_ENCRYPTION_KEY`
   - `REVIEW_ADMIN_PASSWORD`
3. Lancer:

```bash
docker compose -f docker-compose.ovh.yml up -d --build
```

## Verification

Depuis le VPS:

```bash
curl -H 'X-API-Key: ...' http://127.0.0.1:8000/healthz
curl -H 'X-API-Key: ...' http://127.0.0.1:8000/campaigns
```

Depuis le poste local:

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@<vps>
curl -H 'X-API-Key: ...' http://127.0.0.1:8000/healthz
```

## Durcissement ulterieur

- reverse proxy TLS
- secrets hors `.env`
- sauvegarde PostgreSQL
- monitoring
- rotation des credentials
