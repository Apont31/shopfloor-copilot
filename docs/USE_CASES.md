# Backlog des cas d'usage et grille de priorisation

Toutes les notes ci-dessous sont des **estimations a priori, hypothèses à valider** avec les sponsors métier et l'IT lors de la revue mensuelle du portefeuille ([LAB_IA.md](LAB_IA.md)). Aucune n'est issue d'une mesure.

## Grille

Chaque critère est noté de 1 à 5. **5 est toujours la note la plus favorable.**

| Critère | Poids | 1 | 5 |
|---|---|---|---|
| **Valeur** (V) : temps gagné, qualité, coûts évités | 30 % | Gain marginal | Gain fort et récurrent |
| **Faisabilité** (F) : données disponibles, intégration | 25 % | Données absentes ou inexploitables | Données prêtes, intégration simple |
| **Risque** (R) : criticité, réglementation (RGPD, AI Act) | 20 % | Risque élevé, système à haut risque | Risque faible, humain dans la boucle |
| **Délai** (D) : temps jusqu'au premier pilote | 10 % | Plus de 6 mois | Moins d'un mois |
| **Adoption probable** (A) | 15 % | Usage incertain, résistance attendue | Besoin exprimé par les utilisateurs |

**Score = 0,30 × V + 0,25 × F + 0,20 × R + 0,10 × D + 0,15 × A** (sur 5).

**Priorité** : haute si score ≥ 4,0 ; moyenne de 3,0 à 3,99 ; basse sous 3,0.
**Veto** : une note de risque à 1 classe le cas en priorité basse, quel que soit son score.

## Cas d'usage

### 1. Copilote NC (industrie / production) : ce projet, statut MVP

- **Problème** : les fiches de non-conformité sont traitées à la main ; le savoir utile est dispersé entre procédures et anciennes NC.
- **Solution** : oracle déterministe pour le verdict, RAG pour retrouver les cas similaires, LLM local pour rédiger l'action, validation humaine, ticket ERP.
- **Données** : fiches NC à en-tête structuré, tolérances, procédures, gammes, historique NC.
- **Notes** : V 4, F 5, R 4, D 5, A 4. **Score 4,35.** Priorité **haute**.
- **Décision** : **go** pour un pilote sur 1 site, avec mesure du temps réel par fiche.

### 2. Assistant procédures (industrie / production) : en cours

- **Problème** : les opérateurs cherchent longtemps la bonne consigne dans des procédures longues.
- **Solution** : questions-réponses sur les procédures et gammes, réponses citant la section source, « je ne sais pas » si rien n'est trouvé.
- **Données** : procédures et gammes à jour, déjà indexées pour le copilote NC.
- **Notes** : V 4, F 4, R 4, D 4, A 4. **Score 4,00.** Priorité **haute**.
- **Décision** : **go** POC. Réutilise l'index, l'interface et les tests du copilote NC.

### 3. Synthèse des réclamations clients (commerce)

- **Problème** : les réclamations arrivent par plusieurs canaux ; les tendances se voient tard.
- **Solution** : résumé structuré de chaque réclamation (pièce, défaut, gravité), regroupement par thème, lien vers les NC internes.
- **Données** : courriels et formulaires de réclamation, référentiel pièces. Données clients : traitement sur site.
- **Notes** : V 3, F 4, R 3, D 4, A 4. **Score 3,50.** Priorité moyenne.
- **Décision** : **ajuster** : cadrer avec le service client le périmètre des données et la durée de conservation, puis POC.

### 4. OCR des fiches NC papier (industrie / production)

- **Problème** : une partie des fiches est encore remplie à la main et ressaisie.
- **Solution** : lecture des fiches scannées vers l'en-tête structuré, vérification humaine des champs mesurés avant l'oracle.
- **Données** : scans de fiches (qualité variable), modèle de fiche.
- **Notes** : V 3, F 3, R 4, D 4, A 4. **Score 3,45.** Priorité moyenne.
- **Décision** : **ajuster** : compter d'abord la part de fiches papier sur un mois. Si elle est faible, mieux vaut un formulaire numérique.

### 5. Détection de dérive d'épaisseur en peinture (industrie / production)

- **Problème** : une dérive d'épaisseur de couche est détectée quand une pièce sort de tolérance, trop tard.
- **Solution** : cartes de contrôle statistiques sur les mesures d'épaisseur, alerte avant la sortie de tolérance. Règle déterministe, pas de LLM.
- **Données** : historique des mesures de contrôle horodatées, par ligne et par produit.
- **Notes** : V 4, F 3, R 4, D 2, A 3. **Score 3,40.** Priorité moyenne.
- **Décision** : **ajuster** : vérifier que l'historique de mesures est extractible et assez dense, puis POC.

### 6. Assistant d'accueil et de questions RH (RH)

- **Problème** : questions répétées des nouveaux arrivants sur les règles internes et la sécurité.
- **Solution** : questions-réponses limitées aux documents validés par les RH et le service sécurité, sources citées, renvoi vers une personne pour tout cas individuel.
- **Données** : règlement intérieur, consignes sécurité, livret d'accueil. Aucune donnée personnelle.
- **Notes** : V 3, F 4, R 3, D 4, A 3. **Score 3,35.** Priorité moyenne.
- **Décision** : **ajuster** : à construire sur la même base que l'assistant procédures. L'utilisateur doit savoir qu'il parle à une IA (obligation de transparence de l'AI Act).

### 7. Aide au chiffrage des devis en tôlerie (commerce)

- **Problème** : le chiffrage dépend de quelques personnes expérimentées.
- **Solution** : retrouver les pièces similaires déjà chiffrées et proposer une fourchette, avec les devis de référence. Le chiffreur décide.
- **Données** : historique de devis et de coûts réels, plans ou caractéristiques des pièces. Qualité de l'historique inconnue.
- **Notes** : V 4, F 3, R 3, D 2, A 3. **Score 3,20.** Priorité moyenne.
- **Décision** : **ajuster** : audit de l'historique (écarts entre devis et coûts réels) avant tout POC.

### 8. Présélection de candidatures (RH)

- **Problème** : volume de candidatures à trier sur certains postes.
- **Solution envisagée** : tri ou notation automatique des candidatures.
- **Données** : CV et lettres, donc données personnelles.
- **Notes** : V 3, F 2, R 1, D 2, A 2. **Score 2,10.** Priorité **basse** (score et veto risque).
- **Décision** : **stop**. Justification :
  - l'AI Act classe les systèmes d'IA utilisés pour trier ou évaluer des candidatures parmi les **systèmes à haut risque** (annexe III, emploi) : gestion des risques, documentation technique, contrôle humain effectif, journalisation, information des personnes concernées ;
  - le **RGPD** encadre les décisions fondées exclusivement sur un traitement automatisé et impose minimisation et information des candidats ; une analyse d'impact (AIPD) serait très probablement requise ;
  - risque de biais discriminatoire difficile à mesurer sur des volumes faibles ;
  - le coût de conformité dépasse le gain attendu pour un lab IA en phase de démarrage.

## Récapitulatif trié par score

| Rang | Cas d'usage | Domaine | V | F | R | D | A | Score | Priorité | Décision |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Copilote NC | Production | 4 | 5 | 4 | 5 | 4 | 4,35 | Haute | Go pilote 1 site (MVP) |
| 2 | Assistant procédures | Production | 4 | 4 | 4 | 4 | 4 | 4,00 | Haute | Go POC (en cours) |
| 3 | Synthèse des réclamations clients | Commerce | 3 | 4 | 3 | 4 | 4 | 3,50 | Moyenne | Ajuster : cadrage données |
| 4 | OCR des fiches NC papier | Production | 3 | 3 | 4 | 4 | 4 | 3,45 | Moyenne | Ajuster : compter les fiches papier |
| 5 | Dérive d'épaisseur en peinture | Production | 4 | 3 | 4 | 2 | 3 | 3,40 | Moyenne | Ajuster : vérifier l'historique |
| 6 | Assistant d'accueil RH | RH | 3 | 4 | 3 | 4 | 3 | 3,35 | Moyenne | Ajuster : mutualiser avec n° 2 |
| 7 | Aide au chiffrage des devis | Commerce | 4 | 3 | 3 | 2 | 3 | 3,20 | Moyenne | Ajuster : audit de l'historique |
| 8 | Présélection de candidatures | RH | 3 | 2 | 1 | 2 | 2 | 2,10 | Basse (veto) | Stop |

## Conclusion

1. **Finir le pilote du copilote NC** sur un site et mesurer le temps réel par fiche : c'est la preuve qui manque pour décider d'une généralisation.
2. **Lancer le POC de l'assistant procédures** : même index, même interface, mêmes garde-fous, donc un coût marginal faible ; l'assistant RH viendra ensuite sur la même base.
3. **Qualifier les données** des cas 3, 4 et 5 avant tout POC ; la présélection de candidatures reste hors du portefeuille.
