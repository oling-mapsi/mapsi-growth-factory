# Editorial Source Packs

Le lot `MGF-501` ajoute une couche de sources editoriales verifiables avant generation.

## Objets

- `EditorialSourcePack`
- `EditorialSourceItem`
- `EditorialSourceAttachmentReference`

## But

- attacher un ensemble de sources a une campagne hebdomadaire ;
- distinguer ce qui est communicable, anonymisable ou interdit ;
- previsualiser les faits reellement transmis au moteur editorial ;
- ne jamais envoyer les pieces jointes brutes au modele.

## Regles de confidentialite

- `CLIENT_CONFIDENTIAL` et `STRICTLY_CONFIDENTIAL` ne sont jamais transmis tels quels ;
- les contenus projet (`PROJECT_DELIVERABLE`, `CLIENT_FEEDBACK`, `CONSULTANT_NOTE`, `EMAIL_THREAD`, `TEAMS_MESSAGE`, `TEAMS_THREAD`) sont anonymises par defaut ;
- un nom de client n'est conserve que si `client_name_usage_authorized=true` ;
- `prohibited_facts` ne sont jamais exposes au preview editorial.

## API admin

- `POST /api/admin/v1/source-packs`
- `GET /api/admin/v1/source-packs/{id}`
- `PUT /api/admin/v1/source-packs/{id}`
- `POST /api/admin/v1/source-packs/{id}/validate`
- `POST /api/admin/v1/source-packs/{id}/items`
- `PUT /api/admin/v1/source-packs/{id}/items/{itemId}`
- `DELETE /api/admin/v1/source-packs/{id}/items/{itemId}`
- `GET /api/admin/v1/source-packs/{id}/editorial-preview`

## Saisie manuelle

Le mode manuel permet de renseigner :

- resume projet ;
- probleme client ;
- methode OLING ;
- livrables realises ;
- resultats observes ;
- enseignements ;
- CTA souhaite.

Ces champs servent a produire :

- `factual_summary`
- `usable_facts`
- `anonymized_facts`
- `prohibited_facts`

## Audit

Les creations, mises a jour, suppressions d'items et validations sont auditees.
