# Implementation Roadmap Lot 2

Ordre recommande pour `MGF-201` a `MGF-213`, base sur l'etat reel du depot au 2026-07-11.

## Principes d'ordonnancement

- traiter d'abord le contrat commun avant les connecteurs reels;
- isoler LinkedIn et Oling en PRs distinctes si le risque de regression diverge;
- poser la persistance et la securite de publication avant le basculement runtime;
- ne pas remplacer `CompositeSimulatedPublisher` avant validation canal par canal.

## Ordre recommande

1. `MGF-201` - Audit cleanup minimal non fonctionnel
   - corriger la documentation cassée et figer les references d'architecture, notamment `README.md` en conflit et les docs de publication.

2. `MGF-202` - Contrat commun de publication
   - cadrer l'usage reel de `PublisherPort`, `PublishRequest`, `PublishApprovedCampaignRequest` et les resultats attendus par canal.

3. `MGF-203` - Modele de persistance Oling
   - ajouter les tables/colonnes necessaires au suivi des publications `oling`, a l'image de `linkedin_publications` et `mautic_campaign_publications`.

4. `MGF-204` - Resultats et erreurs multi-canaux
   - introduire un stockage explicite des statuts canal par canal pour supprimer l'ambiguite de `publications` seul.

5. `MGF-205` - Kill switches par canal
   - ajouter la configuration et les controles `linkedin` / `oling`, absents aujourd'hui.

6. `MGF-206` - Readiness et preflight unifies
   - aligner `publication_readiness()` avec les controles reels de publication, y compris les gardes canal-specifiques.

7. `MGF-207` - Adaptation LinkedIn au contrat commun
   - reutiliser la logique de `LinkedInPostPublisher` derriere `PublisherPort` sans retirer les routes ops existantes.

8. `MGF-208` - Connecteur Oling reel
   - implementer le connecteur applicatif pour `channel="oling"` et son stockage externe.

9. `MGF-209` - Wiring runtime simulateur/reel
   - remplacer le branchement inline de `CompositeSimulatedPublisher` dans `get_campaign_service()` par une selection explicite de strategie.

10. `MGF-210` - Idempotence de publication Oling
    - ajouter les contraintes de deduplication et les tests d'idempotence equivalentes au niveau LinkedIn.

11. `MGF-211` - Gestion des echecs partiels et reprise
    - definir le comportement quand un canal publie et l'autre echoue, avec retries et etat exploitable.

12. `MGF-212` - Tests end-to-end de publication reelle
    - etendre `tests/integration` pour couvrir le wiring commun et non seulement les routes ops specialisees.

13. `MGF-213` - Bascule de production et retrait progressif du tout-simule
    - activer les publishers reels par configuration, conserver une voie de repli, puis reduire les doublons devenus inutiles.

## Decoupage PR recommande

- PR 1 : `MGF-201` a `MGF-206`
  - socle, migrations, contrat, garde-fous, pas de bascule runtime.

- PR 2 : `MGF-207` a `MGF-210`
  - branchement LinkedIn puis Oling sur le contrat commun.

- PR 3 : `MGF-211` a `MGF-213`
  - robustesse finale, tests end-to-end, activation progressive.

## Migrations a prevoir dans ce roadmap

- persistance Oling;
- statut/resultat par canal si `publications` reste insuffisant;
- eventuels drapeaux de configuration canal;
- eventuels kill switches par canal.

## Tests a exiger sur chaque ticket

- tests unitaires sur le service modifie;
- tests d'integration API sur le endpoint impacte;
- tests d'idempotence si un `POST` ou une publication externe change;
- verification explicite qu'aucune publication non `APPROVED` n'est possible.
