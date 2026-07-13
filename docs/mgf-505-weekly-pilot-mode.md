# MGF-505 Weekly Pilot Mode

## Objectif

Permettre un cycle hebdomadaire pilote sans attendre les connecteurs reels Teams, LinkedIn et mailing.

## Configuration

- `GROWTH_OPERATION_MODE=pilot`
- `PILOT_EMAIL_ALLOWLIST=pilot1@example.test,pilot2@example.test`

Par defaut, la production doit rester en mode sur :

- `GROWTH_OPERATION_MODE=safe`
- `WORKFLOW_KILL_SWITCH=true`
- `PUBLISH_OLING_ENABLED=false`
- `PUBLISH_MAPSI_SITE_ENABLED=false`
- `PUBLISH_LINKEDIN_ENABLED=false`
- `SEND_MAPSI_USERS_ENABLED=false`

## Regles pilot

- `MAPSI_MARKET`
  - generation reelle autorisee
  - previews Oling et MAPSI autorisees
  - publications Oling et MAPSI possibles si approbation, hashes, flags et kill switches sont valides
  - LinkedIn reste brouillon uniquement
- `OLING_PRACTICE`
  - sources manuelles
  - preview Oling autorisee
  - publication Oling possible si les garde-fous standards passent
  - LinkedIn reste brouillon uniquement
- `MAPSI_USERS`
  - generation reelle autorisee
  - preview autorisee
  - aucun envoi vers des utilisateurs MAPSI reels
  - seuls des tests vers `PILOT_EMAIL_ALLOWLIST` sont autorises

## API admin

Le mode est expose via :

- dashboard
- health
- channels

Les reponses retournent :

- `operational_mode`
- `banner_message`

En mode pilot, la banniere vaut `MODE PILOTE`.

## CLI

- `mapsi-growth weekly:create-pilot-pack`
- `mapsi-growth weekly:generate --pack-id=<id>`
- `mapsi-growth weekly:generate --pack-id=<id> --campaign=MAPSI_MARKET`
- `mapsi-growth weekly:status --pack-id=<id>`
- `mapsi-growth weekly:return-to-safe-mode`

## Retour au safe mode

`weekly:return-to-safe-mode` :

- desactive les canaux pilotables
- reactive le kill switch global
- conserve les brouillons existants
- produit un rapport JSON

## Garanties

- aucune publication LinkedIn reelle en mode pilot
- aucun usage de la base utilisateurs MAPSI reelle en mode pilot
- les publications Oling et MAPSI restent soumises aux controles metier existants
