# MAPSI Growth Factory

## Regles de travail Codex

- Toute evolution qui touche `mapsi-v6` et `mapsi-growth-factory` doit etre decoupee en 2 taches Codex.
- Toute evolution cross-repository doit produire 2 branches et 2 pull requests.
- La PR Growth ne doit etre fusionnee qu'apres la PR MAPSI, sauf si Growth reste branche sur un simulateur.
- Aucun couplage implicite entre depots : le contrat HTTP, les schemas et les mocks restent la reference.

## Conventions

- `MGF-100` a `MGF-199` : lot 1
- `MGF-200` a `MGF-299` : lot 2
- `MGF-300` a `MGF-399` : lot 3
- `MGF-400` a `MGF-499` : lot 4

## Branches et PR

- MAPSI : `feature/MGF-xxx-growth-...`
- Growth Factory : `feature/MGF-xxx-mapsi-...`
- Suffixes PR :
- `-A` pour la PR cote MAPSI
- `-B` pour la PR cote Growth Factory

## Contraintes techniques

- Aucun secret commite.
- Toute integration externe reste derriere une interface.
- Toute publication reste bloquee tant que la campagne n'est pas `APPROVED`.
- Toute fonctionnalite doit etre testee.
