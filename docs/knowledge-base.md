# Base de connaissances editoriale minimale

Cette PR ajoute une base de connaissances versionnee sous `knowledge/` pour une V1 editoriale simple.

Contenu :

- `knowledge/mapsi/*` pour les regles et fonctionnalites MAPSI strictement prouvees ;
- `knowledge/oling/*` pour le cadre editorial OLING et les fiches practices ;
- `knowledge/schemas/*` pour les schemas de validation ;
- `knowledge/version.sha256` pour figer la version exploitable.

Commande :

```bash
mapsi-growth knowledge:validate
```

La validation controle :

- presence des fichiers obligatoires ;
- validite YAML et front matter ;
- unicite des `feature_id` ;
- coherence `practice_id` / nom de fichier ;
- presence de sources ;
- absence d'email, de token et de champs secrets ;
- coherence du hash versionne.

Le module Python associe est `app/knowledge` avec :

- `KnowledgeRepository`
- `validate_knowledge_base()`

La PR ne modifie ni les publishers ni le branchement OpenAI.
