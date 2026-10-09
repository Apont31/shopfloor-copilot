# Cadrage — ShopFloor Copilot

Décisions validées à l'étape 1. Toute évolution passe par le chef de projet.

**D1 — L'oracle seul décide de la conformité.**
Code pur, sans LLM, réseau ni horloge. Tolérances lues uniquement dans `config/tolerances.yaml`, bornes incluses, comparaisons en `Decimal`.
Fonction : `check_conformity` (nom imposé par le skill oracle-guard ; la signature exacte reste à fixer, le skill ne la précise pas).
Verdicts : `CONFORME` / `NON_CONFORME` / `INDETERMINE`. Le verdict structuré porte : statut, mesure, tolérance, écart.

**D2 — `parse_nc` est déterministe.**
Il lit les champs structurés de la fiche. Le LLM ne lit pas les mesures.

**D3 — Graphe LangGraph.**
`parse_nc → oracle → [NON_CONFORME] retrieve_similar → propose_action → human_gate (interrupt) → create_ticket`.
`CONFORME` et `INDETERMINE` vont directement à `human_gate`.

**D4 — Le verdict ne transite pas par le LLM.**
`ActionProposal` n'a pas de champ verdict. Le ticket prend son verdict dans l'état (sortie de l'oracle), avec le hash du YAML de tolérances pour la traçabilité.

**D5 — Un seul appel LLM par fiche.**
Dans `propose_action`, sortie JSON validée par Pydantic, une relance au maximum, puis repli déterministe.

**D6 — Données et versions.**
Données 100 % fictives. Un tag git par étape. `pytest -m "not llm"` vert avant chaque tag.

**D7 — Tests obligatoires.**
- Un faux LLM qui contredit le verdict : sa sortie est rejetée.
- Une injection de prompt dans la fiche : sans effet sur le verdict ni sur le flux.
- Un verdict identique avec et sans LLM.
