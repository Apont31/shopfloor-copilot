---
name: oracle-guard
description: À utiliser dès que tu modifies l'oracle de conformité, tolerances.yaml, le nœud propose_action ou les prompts du LLM, pour garantir que le LLM ne décide jamais de la conformité.
---

# Garde-fou de l'oracle

Règle centrale du projet : l'oracle (code pur, tolérances dans tolerances.yaml) décide de la conformité. Le LLM explique et rédige, il ne tranche jamais.

## Contraintes sur l'oracle
- `check_conformity(nc: NCRecord, tolerances: ToleranceTable) -> OracleResult` est une fonction pure : aucune dépendance au LLM, au réseau ni à l'horloge.
- Les tolérances viennent uniquement de tolerances.yaml, jamais codées en dur ailleurs.
- Le verdict a 3 états : CONFORME / NON_CONFORME / INDETERMINE. Il est structuré : statut, mesure, tolérance, écart.
- Tests obligatoires : cas conforme, cas non conforme, valeurs exactement sur les bornes, donnée manquante ou invalide.

## Contraintes sur l'agent
- Le nœud oracle s'exécute avant tout appel au LLM.
- Le verdict est injecté dans le prompt du LLM comme un fait non modifiable.
- Après la réponse du LLM, une vérification en code compare sa sortie au verdict. Si elle le contredit, la sortie est rejetée et l'agent le signale au lieu de continuer.
- Le LLM n'a aucun moyen de modifier le verdict dans l'état de l'agent.

## Tests obligatoires
- Un test avec un faux LLM déterministe qui renvoie volontairement une conclusion contraire au verdict : l'agent doit la rejeter.
- Un test qui vérifie que le verdict est identique avec et sans LLM.

## À signaler dans le rapport
Toute modification de tolerances.yaml, du prompt de propose_action ou de la logique de vérification, avec le test de non-régression associé.
