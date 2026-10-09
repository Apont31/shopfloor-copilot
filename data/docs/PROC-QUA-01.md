---
doc_id: PROC-QUA-01
type: transverse
domaine: qualite
part_ref: null
date: 2024-05-13
version: E
fictif: true
---

# PROC-QUA-01 — Traitement des non-conformités

## Objet
Règles communes à tous les ateliers (composite, tôlerie, peinture) pour déclarer, analyser et clore une non-conformité (NC).

## Déclaration
- Toute mesure hors tolérance, ou tout défaut d'aspect, donne lieu à une fiche NC le jour même.
- La conformité est jugée uniquement par rapport aux tolérances de la procédure du procédé concerné. Une caractéristique sans tolérance définie est classée « indéterminée » et transmise au service qualité.
- Les pièces suspectes sont isolées et étiquetées en rouge en zone NC.

## Décisions possibles
| Décision | Quand | Qui valide |
|---|---|---|
| Retouche | Le défaut peut être repris et la pièce recontrôlée conforme | Chef d'atelier |
| Rebut | Le défaut est structurel ou ne peut pas être repris | Responsable qualité |
| Dérogation | La pièce reste hors tolérance mais reste utilisable | Responsable qualité et bureau d'études, avec accord écrit du client |

Aucune décision ne peut être appliquée sans validation humaine de la personne désignée.

## Ticket ERP
Chaque NC validée crée un ticket ERP avec les champs suivants :
- numéro de NC, référence pièce, lot, procédé ;
- caractéristique, valeur mesurée, tolérance appliquée ;
- verdict de conformité ;
- action corrective proposée et décision (retouche, rebut ou dérogation) ;
- nom du valideur et date de validation.

## Clôture
La NC est close quand l'action corrective est réalisée et que son efficacité est vérifiée sur les lots suivants.
