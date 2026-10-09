---
name: non-regression
description: À utiliser avant et après toute modification de code existant, pour vérifier que ce qui fonctionnait fonctionne encore et prévoir le retour arrière.
---

# Non-régression

Ne casse jamais ce qui fonctionne déjà.

## Avant la modification
1. Lance toute la suite de tests (`pytest`) et note le résultat de départ : nombre de tests réussis et échoués.
2. Si un test échoue déjà avant ta modification, signale-le dans le rapport et ne le « répare » pas en douce.
3. Liste les scénarios existants que ta modification peut toucher (oracle, retrieval, agent, API).

## Après la modification
1. Relance toute la suite de tests et compare avec le résultat de départ.
2. Si un test qui passait échoue maintenant, arrête-toi, annule ta modification et explique la cause dans le rapport.
3. Ne modifie jamais un test existant pour le faire passer sans le dire explicitement dans le rapport.
4. Pour chaque bug corrigé, ajoute un test qui échouait avant la correction.

## Retour arrière
- Donne dans le rapport la commande git de retour arrière (par exemple revenir au dernier tag), à lancer par Antoine dans son second onglet de terminal.
- Ne lance pas toi-même de commande git destructrice.
