# Lab IA : cadre test & learn

Objectif : tester vite, arrêter tôt ce qui ne marche pas, et n'étendre que ce qui est réellement utilisé.

## Le cycle

| Étape | Durée | Livrable | Question à trancher |
|---|---|---|---|
| **Idée** | - | Une ligne dans le backlog ([USE_CASES.md](USE_CASES.md)) | Le problème est-il réel et fréquent ? |
| **Fiche cas d'usage** | 1 page | Problème, utilisateurs, données, risques, critères de succès chiffrés | Vaut-il un POC ? |
| **POC** | 2 semaines maximum | Prototype sur données fictives ou extraites, mesures face aux critères | La technique tient-elle ? |
| **MVP** | Pilote sur 1 site | Outil utilisé au quotidien, indicateurs suivis | Les utilisateurs l'adoptent-ils ? |
| **Industrialisation** | Selon le cas | CI/CD, supervision, sauvegardes, formation, documentation | Peut-on l'exploiter sans l'équipe projet ? |
| **Généralisation** | Site par site | Déploiement multi-sites, référents formés | Le gain se confirme-t-il ailleurs ? |

Les critères de succès du POC sont écrits **avant** de commencer. Exemple de forme, seuils indicatifs : « sur 20 fiches de test, 0 verdict faux, 80 % des propositions jugées utilisables sans réécriture complète, moins de 30 s par fiche ». Les seuils sont fixés par le sponsor métier, pas par l'équipe technique.

## Décision à chaque passage : go / ajuster / stop

| Décision | Quand | Ce qui se passe |
|---|---|---|
| **Go** | Tous les critères chiffrés sont atteints, aucun risque bloquant ouvert | Étape suivante, budget associé |
| **Ajuster** | Critères partiellement atteints, cause identifiée et corrigeable | Une seule itération supplémentaire, même durée, critères inchangés |
| **Stop** | Critère majeur manqué sans piste crédible, données indisponibles, risque réglementaire non maîtrisé, ou adoption faible au pilote | Arrêt, fiche de retour d'expérience d'une page, cas archivé |

Deux « ajuster » de suite sur la même étape valent un stop. Un stop documenté est un résultat, pas un échec.

## Rôles

- **Sponsor métier** : porte le problème, fixe les critères de succès, prend la décision go / ajuster / stop.
- **Référent site** : choisit les utilisateurs pilotes, remonte les retours terrain, vérifie que l'outil colle aux pratiques réelles.
- **Data scientist** : conçoit et construit le POC puis le MVP, mesure, documente les limites.
- **IT / ERP** : accès aux données, intégration, sécurité, hébergement sur site, exploitation après industrialisation.
- **Utilisateurs pilotes** : utilisent l'outil sur leur travail réel, signalent ce qui ne va pas.

## Rituels

- **Démo toutes les 2 semaines** : 20 minutes, sur l'outil réel, devant le sponsor et le référent site. On montre ce qui marche et ce qui ne marche pas.
- **Revue mensuelle du portefeuille** : backlog re-noté avec la grille de [USE_CASES.md](USE_CASES.md), décisions go / ajuster / stop, au plus 2 ou 3 cas actifs en même temps.

## Principes

1. **Données sur site quand c'est sensible.** Modèles locaux, aucun envoi vers un service externe pour des données de production, RH ou clients.
2. **Humain dans la boucle pour toute décision qui engage** : qualité, commande, client, personne. L'outil propose, une personne nommée valide, la validation est tracée.
3. **Règle déterministe chaque fois qu'une règle existe.** Une tolérance, un barème ou un seuil se codent et se testent. Le LLM sert à rédiger, résumer et retrouver, pas à trancher.
4. **Mesurer l'adoption avant d'étendre.** Un outil peu utilisé sur un site ne sera pas mieux utilisé sur cinq.

## Comment ShopFloor Copilot illustre ce cycle

- **Fiche cas d'usage** : [CADRAGE.md](CADRAGE.md) fixe les décisions de départ, dont la règle centrale : l'oracle seul décide de la conformité.
- **POC (v0.1 → v0.7)** : squelette, corpus fictif, oracle déterministe, RAG, fausse API ERP, agent, test de bout en bout. Chaque brique est taguée et testée.
- **Consolidation (v0.7.1 → v1.0)** : tests de valeurs limites, garde-fou, finitions, puis tag `v1.0-mvp`.
- **MVP utilisable (v1.1 → v1.2)** : traitement de la boîte de réception, file de validation, journal, puis interface pour le responsable qualité.
- **Mesure d'adoption** : l'écran Pilotage calcule, à partir du journal, la part de propositions approuvées telles quelles, modifiées ou rejetées, par site et par procédé. Un taux de modification élevé sur un site dit où la proposition est mal adaptée ; un site sans décisions dit où l'outil n'est pas utilisé. C'est la donnée qui manque le plus souvent pour décider d'une généralisation.
- **Ce qui n'est pas encore fait** : le pilote réel. Le temps gagné affiché dans le Pilotage est une **hypothèse paramétrable**, pas une mesure : le journal n'enregistre pas le temps passé par le valideur. Le mesurer est le premier critère à fixer pour un vrai pilote.
