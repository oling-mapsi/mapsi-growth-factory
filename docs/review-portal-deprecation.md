# Review Portal Deprecation

## Objectif

Le portail transitoire `growth.oling.fr` reste disponible le temps de la bascule vers MAPSI Studio, mais il est piloté par `REVIEW_PORTAL_MODE` pour limiter progressivement son usage.

## Modes

- `enabled`
  L'interface historique reste disponible.

- `readonly`
  La consultation est autorisée.
  Aucune décision n'est acceptée.
  L'interface affiche que l'administration a été déplacée dans MAPSI Studio et les actions sont redirigées vers Studio.

- `emergency-only`
  L'interface n'est utilisable que pour le secours.
  L'accès exige :
  une authentification review valide ;
  un utilisateur présent dans `REVIEW_PORTAL_EMERGENCY_ALLOWLIST` ;
  un en-tête `X-Review-Emergency-Key` conforme à `REVIEW_PORTAL_EMERGENCY_KEY`.

- `disabled`
  L'interface publique de review est désactivée.
  Une page informe que l'administration a été déplacée dans MAPSI Studio.

## Variables

- `REVIEW_PORTAL_MODE`
- `REVIEW_PORTAL_STUDIO_URL`
- `REVIEW_PORTAL_EMERGENCY_ALLOWLIST`
- `REVIEW_PORTAL_EMERGENCY_KEY`
- `REVIEW_PORTAL_EMERGENCY_BANNER`

## Réactivation d'urgence

1. Passer `REVIEW_PORTAL_MODE=emergency-only`.
2. Définir strictement `REVIEW_PORTAL_EMERGENCY_ALLOWLIST`.
3. Définir ou tourner `REVIEW_PORTAL_EMERGENCY_KEY`.
4. Communiquer la clé hors canal applicatif.
5. Vérifier les audits `review.portal_emergency_access_granted` et `review.portal_emergency_access_denied`.
6. Revenir à `readonly` ou `disabled` dès la fin de l'incident.

## Portée

Cette dépréciation ne coupe pas :

- l'API Growth ;
- les health checks ;
- les webhooks ;
- les communications internes nécessaires.
