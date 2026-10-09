---
doc_id: PROC-TOL-01
type: procedure
domaine: tolerie
part_ref: SE-450
date: 2024-06-03
version: D
fictif: true
---

# PROC-TOL-01 — Pliage du support SE-450 en inox 304L épaisseur 2 mm

## Objet
Mise en forme du support SE-450 à partir d'un flan découpé laser en tôle inox 304L de 2 mm : pliage sur presse-plieuse à commande numérique, puis contrôle dimensionnel.

## Préparation
- Vérifier que le numéro de lot matière inscrit sur le flan correspond au certificat matière du lot.
- Outillage : poinçon et matrice dédiés à l'inox. Nettoyer les outils pour éviter toute pollution par de l'acier noir.
- Charger le programme de pliage SE-450 de la presse. Ne pas modifier la compensation de retour élastique sans validation du régleur.

## Pliage
- Plier dans l'ordre du programme, film de protection côté visible.
- **Changement de lot matière** : l'inox d'un nouveau lot peut présenter un retour élastique différent. À chaque nouveau lot, plier une première pièce, la mesurer complètement (contrôle du premier article) et ajuster la compensation de la presse-plieuse avant de lancer la série.

## Contrôle
- Angle de pli au rapporteur numérique, sur la première pièce puis une pièce sur dix.
- Longueur au pied à coulisse.
- Planéité sur marbre, avec cales étalons.
- Toute valeur hors tolérance déclenche une fiche de non-conformité selon PROC-QUA-01.

## Tolérances
<!-- TOLERANCES:START -->
| Caractéristique | Unité | Nominal | Min | Max | Résolution |
|---|---|---|---|---|---|
| angle_pli | deg | 90.0 | 89.5 | 90.5 | 0.1 |
| longueur | mm | 250.0 | 249.7 | 250.3 | 0.1 |
| planeite | mm | — | — | 0.50 | 0.01 |
<!-- TOLERANCES:END -->
