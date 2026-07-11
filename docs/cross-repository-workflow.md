# Workflow Cross-Repository

## Regle

Une evolution qui touche `mapsi-v6` et `mapsi-growth-factory` produit :

1. une tache Codex cote MAPSI
2. une tache Codex cote Growth Factory
3. une PR MAPSI
4. une PR Growth Factory

## Exemple

Ticket : `MGF-102`

Cote MAPSI :

- branche : `feature/MGF-102-growth-usage-api`
- PR : `MGF-102-A — Add MAPSI Growth usage API`

Cote Growth Factory :

- branche : `feature/MGF-102-mapsi-usage-connector`
- PR : `MGF-102-B — Consume MAPSI Growth usage API`

## Regle de fusion

- Fusionner la PR Growth apres la PR MAPSI.
- Si ce n'est pas possible, la PR Growth doit rester compatible avec un serveur simule.

## Labels GitHub

Le manifeste a appliquer dans les deux depots est defini dans [../.github/labels.yml](../.github/labels.yml).

## Ticketing

- `MGF-100` a `MGF-199` : `lot-1`
- `MGF-200` a `MGF-299` : `lot-2`
- `MGF-300` a `MGF-399` : `lot-3`
- `MGF-400` a `MGF-499` : `lot-4`

## Contrat inter-applications

- Le MCP GitHub peut donner du contexte de lecture.
- Le MCP GitHub ne remplace pas le contrat applicatif.
- Le contrat reste porte par Git, les schemas, les tests et les simulateurs.
