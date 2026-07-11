# Workflows n8n lot 1

Fichiers :

- `n8n/workflows/L1-01-Collect-Product-Changes.json`
- `n8n/workflows/L1-02-Collect-MapsI-Usage.json`
- `n8n/workflows/L1-03-Sync-Mautic-Contacts.json`
- `n8n/workflows/L1-04-Generate-Campaign.json`
- `n8n/workflows/L1-05-Request-Approval.json`
- `n8n/workflows/L1-06-Publish-Approved-Campaign.json`
- `n8n/workflows/L1-07-Collect-Campaign-Metrics.json`
- `n8n/workflows/L1-08-Failure-Notification.json`

Principes :

- tous les appels passent par l'API Growth ;
- aucune regle metier n'est dupliquee dans n8n ;
- chaque execution porte un `correlation_id` ;
- chaque commande `POST` porte une cle d'idempotence ;
- les retries et timeouts sont definis sur les noeuds HTTP ;
- la reprise apres validation humaine passe par le `Wait` webhook de `L1-05`.

Import :

```bash
python3 scripts/validate_n8n_workflows.py
```

Puis dans n8n :

1. importer les huit JSON ;
2. definir `N8N_GROWTH_BASE_URL` et `N8N_GROWTH_API_KEY` ;
3. garder `active=false` tant que l'environnement sandbox n'est pas branche ;
4. tester chaque workflow via `Manual Trigger` ;
5. n'activer le declenchement hebdomadaire qu'apres verification de `Europe/Paris`.

Mode sandbox :

- `N8N_GROWTH_BASE_URL` pointe vers l'API locale Growth ;
- `MAUTIC_BASE_URL` pointe vers un Mautic simule ;
- `MAILPIT` capte les emails de test ;
- aucun destinataire externe n'est autorise.

Reprise apres erreur partielle :

1. identifier le `correlation_id` dans les logs ;
2. verifier l'etape echouee dans `L1-08-Failure-Notification` ;
3. relancer uniquement le sous-workflow concerne avec la meme cle d'idempotence si l'appel precedent est incertain ;
4. si l'approbation humaine etait en attente, reprendre via le webhook du noeud `Wait` ;
5. recontroler `publication-readiness` avant toute republication.
