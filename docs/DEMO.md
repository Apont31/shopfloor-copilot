# Démo en 2 minutes (ligne de commande)

Deux terminaux : **T1** pour le serveur ERP, **T2** pour les commandes. Environnement Python activé dans les deux.

## Préparation (hors caméra)

```bash
# T2 : repartir d'un ERP vide
rm erp.db                       # PowerShell : Remove-Item erp.db
python -m shopfloor.cli ingest

# T1 : serveur ERP
python -m uvicorn shopfloor.erp.api:app --port 8000

# T2 : passage à vide pour charger le modèle sur le GPU (rejet : aucun ticket créé)
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Démo" --decision reject
cls                             # Linux : clear
```

## Déroulé

**1. NC-2026-101, approuvée (environ 40 s)**

```bash
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Chef d'atelier fictif" --decision approve
```

- Tableau : « L'oracle compare la porosité à la tolérance du YAML : 2,8 % pour 2 % maximum. C'est lui qui tranche, pas le LLM. »
- Documents similaires : « Le RAG retrouve une ancienne NC sur la même pièce et la procédure concernée. »
- Proposition : « Le LLM local rédige la cause et l'action, en citant ses sources. Aucun appel cloud. »
- Ticket : « Après validation humaine, le ticket est créé dans l'ERP, avec la trace des tolérances appliquées. »

**2. NC-2026-102, CONFORME (environ 15 s)**

```bash
python -m shopfloor.cli process data/nc_inbox/NC-2026-102.md --valide-par "Chef d'atelier fictif"
```

Taper `a` (approuver).

- « Toutes les mesures sont dans les tolérances. Pas de recherche ni d'appel LLM : une proposition fixe suffit. Le valideur approuve, et un ticket trace la clôture de la fausse alerte. Une NC laisse toujours une trace. »

**3. NC-2026-103, INDETERMINE, action modifiée (environ 40 s)**

```bash
python -m shopfloor.cli process data/nc_inbox/NC-2026-103.md --valide-par "Chef d'atelier fictif"
```

Taper `m`, puis par exemple : `Isoler la pièce, faire définir une tolérance de rugosité pour SE-450, réévaluer la fiche.`

- Tableau : « La rugosité n'a pas de tolérance dans le référentiel. L'oracle ne devine pas : il répond INDETERMINE. »
- Saisie : « Le valideur garde la main : il corrige l'action avant la création du ticket. »

**4. NC-2026-101 relancée, doublon (environ 10 s)**

```bash
python -m shopfloor.cli process data/nc_inbox/NC-2026-101.md --valide-par "Chef d'atelier fictif" --decision approve
```

- « La fiche est déjà traitée : l'agent s'arrête avant l'oracle et le LLM. Aucun doublon dans l'ERP. »

## Conseils d'enregistrement

- Outil : Xbox Game Bar (`Win+Alt+R` pour démarrer et arrêter) ou OBS.
- Police du terminal : 16 au minimum. Fenêtre en plein écran, fond sombre.
- Préparer les commandes dans un bloc-notes et les coller une à une.
- Le premier appel LLM de la démo doit suivre le passage à vide : sinon, le chargement du modèle ajoute plusieurs secondes.
