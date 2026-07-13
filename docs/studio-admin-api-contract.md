# Studio Admin API Contract

Branche: `feature/MGF-402-studio-admin-api-contract`

## Objectif

Expose une API d'administration versionnee en lecture seule pour MAPSI Studio, sans dupliquer la logique metier deja en place dans :

- `CampaignService`
- `ReviewPortalService`
- les repositories de publication et d'audit

Prefixe :

- `/api/admin/v1`

## Principes

- aucune route d'ecriture dans cette PR ;
- aucun modele SQL interne expose directement ;
- DTO dedies Studio ;
- filtrage, pagination et tri cote API ;
- `correlation_id` dans chaque reponse JSON ;
- `ETag` sur les lectures pour supporter `If-None-Match` ;
- pas de secrets, tokens, mots de passe, emails d'audience, prompts systeme ni stack traces.

## Authentification Studio

- authentification serveur a serveur distincte du portail public `/review/*` ;
- `Authorization: Bearer <jwt>` attendu sur `/api/admin/v1/*` ;
- JWT court signe par MAPSI Studio avec une cle privee non stockee dans Growth ;
- verification cote Growth de `alg`, `kid`, signature, `iss`, `aud`, `sub`, `roles`, `iat`, `nbf`, `exp`, `jti` ;
- permissions applicatives derivees d'un mapping roles MAPSI -> permissions Growth ;
- rejeu bloque via enregistrement des `jti` si `STUDIO_ADMIN_ENFORCE_REPLAY_PROTECTION=true` ;
- allowlist reseau complementaire possible via `STUDIO_ADMIN_ALLOWED_IP_RANGES`.

## Contrat

Fichier genere :

- `contracts/studio-admin/openapi.yaml`

Endpoints couverts :

- `GET /api/admin/v1/dashboard`
- `GET /api/admin/v1/campaigns`
- `GET /api/admin/v1/campaigns/{campaignId}`
- `GET /api/admin/v1/campaigns/{campaignId}/assets`
- `GET /api/admin/v1/assets/{assetId}`
- `GET /api/admin/v1/assets/{assetId}/versions`
- `GET /api/admin/v1/assets/{assetId}/evidence`
- `GET /api/admin/v1/assets/{assetId}/preview`
- `GET /api/admin/v1/assets/{assetId}/publication`
- `GET /api/admin/v1/channels`
- `GET /api/admin/v1/audit-events`
- `GET /api/admin/v1/health`

## Notes d'implementation

- la logique de readiness et d'approbation reste portee par `ReviewPortalService` ;
- les vues publication reutilisent les repositories deja presents pour Oling, LinkedIn et Mautic ;
- l'endpoint `versions` expose l'etat courant, la vue review courante et la vue publication connue ; il ne cree pas un nouvel historique persistant dans cette PR.

## Rollback

- retirer le routeur `studio_admin` de `app/main.py` ;
- supprimer le getter `get_studio_admin_service` ;
- supprimer les fichiers `contracts/studio-admin/*`, tests et DTO associes.
