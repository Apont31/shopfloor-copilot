# Démo en 2 minutes (interface)

Trois terminaux, environnement Python activé : **T1** serveur ERP, **T2** interface, **T3** préparation.

## Préparation (hors caméra)

```bash
# T3 : bases vides (interface arrêtée, sinon Windows verrouille les fichiers)
rm -f erp.db shopfloor_state.db* shopfloor_journal.db*
# PowerShell : Remove-Item erp.db, shopfloor_state.db*, shopfloor_journal.db* -ErrorAction SilentlyContinue
python -m shopfloor.cli ingest

# T1 : serveur ERP
python -m uvicorn shopfloor.erp.api:app --port 8000

# T3 : passage à vide pour charger le modèle sur le GPU (rejet : aucun ticket, rien dans le journal)
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Démo" --decision reject

# T2 : interface
python -m streamlit run src/shopfloor/ui/app.py
```

Ouvrir **http://127.0.0.1:8501** (pas `localhost` : l'interface n'écoute que sur 127.0.0.1). Vérifier les trois voyants verts et saisir un nom dans « Valideur ». Navigateur en plein écran, zoom à 110 %.

## Déroulé

| # | Écran | Geste | Phrase |
|---|---|---|---|
| 1 | Boîte de réception | Cliquer « Analyser les nouvelles fiches » | « Les quinze fiches sont analysées en local : un calcul fixe donne chaque verdict, le LLM ne rédige que pour les non-conformes. » |
| 2 | Carte NC-2026-101, Non conforme | Montrer le tableau, les sources, puis « Approuver » | « 2,8 % de porosité pour 2 % maximum : c'est l'oracle qui tranche ; le LLM rédige l'action en citant l'ancienne NC et la procédure, et je valide. » |
| 3 | Carte NC-2026-103, Indéterminé | « Modifier », saisir l'action ci-dessous, « Envoyer » | « Aucune tolérance de rugosité pour cette pièce : l'oracle ne devine pas, et je précise l'action avant que le ticket parte. » |
| 4 | Pilotage | Survoler les indicateurs et la barre « Par site » | « Le Pilotage mesure l'adoption, site par site ; le temps gagné reste une hypothèse, affichée comme telle. » |
| 5 | Tickets ERP | Montrer les deux lignes | « Deux tickets, chacun avec son valideur et l'empreinte des tolérances appliquées : rien n'est écrit sans validation humaine. » |

Action pour l'écran 3 : `Isoler la pièce, faire définir une tolérance de rugosité pour SE-450, réévaluer la fiche.`

## Conseils d'enregistrement

- L'analyse des quinze fiches dure plus longtemps que la démo : couper l'enregistrement pendant l'analyse et reprendre sur le récapitulatif.
- Outil : Xbox Game Bar (`Win+Alt+R`) ou OBS. Une seule fenêtre de navigateur à l'écran.
- Préparer l'action de l'écran 3 dans un bloc-notes pour la coller.

## Annexe : version ligne de commande

Mêmes préparations (sans T2), puis dans T3 :

```bash
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Chef d'atelier fictif" --decision approve
python -m shopfloor.cli process data/nc_inbox/NC-2026-103.md --valide-par "Chef d'atelier fictif"   # taper m, puis l'action
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Chef d'atelier fictif" --decision approve   # doublon refusé
```

Ou en mode boîte de réception : `run-inbox`, `pending`, puis `decide NC-2026-101 approve --valide-par "..."`.
