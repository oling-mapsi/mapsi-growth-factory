# Mise a jour du contrat MAPSI

## Objectif

Synchroniser dans `mapsi-growth-factory` un contrat MAPSI versionne sans dependre du depot local `mapsi-v6`.

## Pre-requis

- un ref explicite : `tag`, `branch` ou `sha`
- des artefacts publies cote MAPSI dans `docs/growth-contract/published`
- aucun secret requis pour cette PR

## Commande

```bash
make contracts-sync MAPSI_REF_TYPE=tag MAPSI_REF=v1.2.0
```

Exemples :

```bash
make contracts-sync MAPSI_REF_TYPE=branch MAPSI_REF=feature/MGF-104-growth-contract
make contracts-sync MAPSI_REF_TYPE=sha MAPSI_REF=0123456789abcdef0123456789abcdef01234567
```

## Garantie de tracabilite

- le SHA resolu est enregistre dans `contracts/mapsi/contract-version.txt`
- aucune synchronisation implicite sur `main` n'est autorisee
- la version fonctionnelle du contrat est lue depuis `openapi.yaml`

## Verification

```bash
make contracts-check
```

Cette verification couvre :

- validation des exemples synthetiques contre les schemas JSON
- presence des champs obligatoires
- rejet des donnees interdites
- rejection d'une version majeure incompatible via les tests

## Serveur mock local

```bash
make mapsi-mock
```

Le mock sert :

- une API de contrat synthetique pour le client type
- des endpoints de type GitHub Raw/API pour tester la synchronisation sans acces reel
