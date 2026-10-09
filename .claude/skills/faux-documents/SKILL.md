---
name: faux-documents
description: À utiliser pour générer ou modifier le corpus fictif (procédures, gammes, anciennes fiches de non-conformité) qui alimente le RAG et l'oracle.
---

# Corpus de faux documents

Tout est fictif : aucune donnée réelle, aucun vrai nom d'entreprise, de client ou de personne.

## Contenu
- Environ 10 documents Markdown dans `data/docs/`.
- Trois domaines : matériaux composites, tôlerie, peinture industrielle.
- Trois types : procédure, gamme de fabrication, ancienne fiche de non-conformité (NC).
- Chaque fichier commence par un en-tête : identifiant (par exemple NC-0001, PROC-003), domaine, type, date fictive.

## Cohérence avec l'oracle
- `tolerances.yaml` est la source de vérité des valeurs chiffrées (épaisseur de peinture, température de cuisson, épaisseur de tôle, etc.).
- Chaque valeur citée dans un document doit être cohérente avec ce fichier. Ne copie pas une valeur de tête : relis le YAML.
- Si tu changes une tolérance, mets à jour les documents concernés et relance les tests.

## Cohérence avec le RAG
- Inclus quelques paires de documents proches (une NC ancienne et une procédure qui la traite) pour que les tests de retrieval aient une réponse attendue connue.
- Garde chaque document assez court pour être découpé proprement (une à deux pages).
- Écris en français, avec le vocabulaire d'atelier, sans jargon inutile.

## Vérification
- Ajoute ou lance un petit script qui contrôle que chaque document a son en-tête et que les valeurs chiffrées respectent le YAML.
- Mentionne dans le README que toutes les données sont fictives.
