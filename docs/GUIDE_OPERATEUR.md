# Guide opérateur : responsable qualité

## Ce que fait l'outil, et ce qu'il ne fait pas

- **Il fait** : lire les nouvelles fiches NC, comparer les mesures aux tolérances, retrouver les cas et procédures similaires, rédiger un brouillon de cause et d'action, créer le ticket ERP **après votre décision**.
- **Il ne décide pas de la conformité** : le verdict vient d'un calcul fixe sur les tolérances du référentiel, jamais du LLM.
- **Il ne crée aucun ticket sans validation** : rien n'est écrit dans l'ERP tant que vous n'avez pas cliqué « Approuver » ou « Envoyer ».

## Routine quotidienne

1. **Vérifier les voyants** de la barre latérale : Ollama, ERP et Index RAG doivent être verts.
2. **Saisir votre nom** dans « Valideur » : il est inscrit sur chaque ticket.
3. **Cliquer « Analyser les nouvelles fiches »** et attendre la fin : jusqu'à une quinzaine de secondes par fiche non conforme sur le poste de démo.
4. **Traiter la file** : les cartes sont triées par gravité (non conformes d'abord). Filtres par site et par verdict si besoin. Pour chaque carte : Approuver, Modifier ou Rejeter.
5. **Regarder « En erreur »** en bas de page, puis l'écran **Tickets ERP** pour vérifier ce qui a été créé.

## Lire une carte

- **Pastille et tableau « Mesures et verdict de l'oracle »** : le verdict **fait foi**. Si vous le pensez faux, c'est la mesure ou la tolérance qui est en cause : ne le contournez pas, signalez-le au responsable du référentiel de tolérances.
- **Documents similaires** : anciennes NC et procédures retrouvées, avec leur score. « Passages retrouvés » montre le texte exact.
- **Proposition** : c'est un **brouillon à vérifier**. « Origine : LLM » veut dire rédigée par le modèle ; « Origine : Déterministe » veut dire texte fixe (fiche conforme ou indéterminée, ou sortie du LLM rejetée par le garde-fou, signalée par un bandeau d'alerte).
- **Sources** : les documents cités par la proposition. Tout élément de l'action doit se retrouver dans une source.

## Modifier ou rejeter ?

- **Modifier** quand le fond est juste mais un détail est faux ou absent. Exemple : l'action cite « op. 50 de PROC-COMP-01 » ; ouvrez la gamme de la pièce (GAMME-CP210) pour vérifier le numéro d'opération, corrigez le texte, puis « Envoyer ». Le ticket porte votre texte.
- **Rejeter** quand la proposition est hors sujet ou que la fiche elle-même est fausse (mesure mal saisie, mauvaise pièce). Aucun ticket n'est créé. Écrivez toujours la raison dans « Commentaire » : c'est ce qui permet d'améliorer l'outil.
- **Indéterminé** : une caractéristique n'a pas de tolérance. La proposition est l'escalade prévue par PROC-QUA-01 ; approuvez-la ou précisez-la.

## Assistant procédures

- Posez votre question dans la page **Assistant procédures**, par exemple « porosité max du CP-210 » ou « que faire au changement de lot matière ? ». Chaque réponse affiche son origine et ses sources.
- **Référentiel** : tolérance lue dans le référentiel, elle fait foi. **LLM** : réponse rédigée à partir des documents cités ; vérifiez-la dans « Passages ». **Extraits** : le modèle n'a pas donné de réponse fiable, lisez les extraits proposés.
- « Je ne trouve pas cette information dans les documents » : la réponse n'est pas dans le corpus. Ne cherchez pas à la faire inventer, signalez le manque au référent.
- Après un nouvel `ingest`, l'interface doit être redémarrée pour voir le nouvel index. Mieux : lancer `ingest` **avant** l'interface.

## Voyant rouge : quoi faire

| Voyant | Message | Action |
|---|---|---|
| Ollama | Ollama indisponible | Lancer l'application Ollama sur le poste |
| ERP | ERP indisponible | Lancer le serveur ERP, ou prévenir l'IT |
| Index RAG | Index RAG indisponible | Faire lancer `python -m shopfloor.cli ingest` par le référent |

Puis cliquer « Revérifier ». Les fiches touchées pendant la panne passent dans « En erreur » : cliquez « Relancer », puis « Analyser les nouvelles fiches ». Une décision refusée faute d'ERP n'est pas perdue : la fiche reste en attente.

## Plan de formation de 30 minutes

| Temps | Contenu |
|---|---|
| 5 min | **Pourquoi** : gagner du temps de rédaction, homogénéiser les actions entre sites. L'oracle tranche, le LLM rédige, vous validez. |
| 10 min | **Démo** : analyse, carte non conforme approuvée, carte indéterminée modifiée, Pilotage, Tickets ERP. |
| 10 min | **Pratique** : chaque participant traite 3 fiches fictives (une à approuver, une à modifier, une à rejeter). |
| 5 min | **Questions**, et rappel de la boucle de retours. |

**Suivi d'adoption** : le référent site consulte chaque semaine l'écran **Pilotage** : fiches traitées, part approuvée telle quelle, modifiée ou rejetée, par site et par procédé. Beaucoup de modifications sur un procédé : la proposition y est mal adaptée. Peu de décisions sur un site : l'outil n'y est pas utilisé.

**Boucle de retours** : les commentaires de rejet et de modification sont relus à chaque démo de quinzaine ; les corrections (procédures, tolérances, consignes au modèle) sont décidées en revue mensuelle.
