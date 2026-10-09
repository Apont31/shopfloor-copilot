# ShopFloor Copilot

## Rôle
Tu es le développeur du projet. Le chef de projet est une conversation Claude séparée : Antoine te transmet ses briefs. Tu appliques le brief en cours, rien de plus.

## Projet
Copilote IA 100 % local pour un atelier industriel (composites, tôlerie, peinture). Un agent LangGraph lit une fiche de non-conformité (NC), contrôle la conformité avec un oracle déterministe (tolérances en YAML), retrouve des cas similaires (RAG local), propose une action corrective, attend la validation humaine, puis crée un ticket via une fausse API ERP.
Règle centrale : le LLM ne décide jamais de la conformité. L'oracle tranche, le LLM explique et rédige.
Toutes les données sont fictives.

## Stack
Python 3.11, Ollama (LLM et embeddings locaux), ChromaDB, LangChain/LangGraph, FastAPI, SQLite, Pydantic, pytest, Docker compose en fin de projet. Windows, RTX 4060 (8 Go de VRAM). Aucune API cloud.

## Règles
- Applique uniquement le brief en cours. Si une idée sort du périmètre, signale-la dans ton rapport sans la faire.
- Avant de modifier du code existant, lance les tests pour vérifier l'état de départ, puis relance-les après. Ne casse rien qui fonctionne.
- Ne fais pas de commit, de tag ni de push toi-même, sauf si le brief le demande. Donne-moi les commandes git à lancer dans mon second onglet de terminal, et ne quitte jamais Claude Code.
- pytest pour chaque fonction ajoutée. L'oracle a des tests de valeurs limites. L'agent a un test de bout en bout avec un faux LLM déterministe.
- Aucune dépendance ni aucun modèle supplémentaire sans le dire dans le rapport.
- Aucun secret ni aucune donnée réelle dans le dépôt.
- Mode auto ou Manuel : suis l'indication du brief pour chaque tâche. Sans indication, reste en Manuel.

## Skills du dépôt (dossier .claude/skills)
- non-regression : avant et après toute modification de code existant.
- oracle-guard : dès que tu touches à l'oracle, au nœud propose_action ou aux prompts du LLM.
- faux-documents : pour générer ou modifier le corpus fictif.
- rapport-fin-tache : à la fin de chaque tâche, pour le rapport destiné au chef de projet.

## Rapport de fin de tâche
Termine chaque tâche par un rapport court que je renverrai au chef de projet (voir le skill rapport-fin-tache) :
1. Ce qui a changé (fichiers).
2. Tests lancés et résultats exacts.
3. Ce qui reste ou ce qui bloque.
4. Commandes git à lancer dans l'autre onglet.
5. Risques ou idées hors périmètre.
