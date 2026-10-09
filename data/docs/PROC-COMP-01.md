---
doc_id: PROC-COMP-01
type: procedure
domaine: composite
part_ref: CP-210
date: 2024-09-16
version: C
fictif: true
---

# PROC-COMP-01 — Drapage et cuisson autoclave du panneau CP-210

## Objet
Fabrication du panneau sandwich CP-210 en préimprégné carbone/époxy : drapage manuel, mise sous vide, cuisson en autoclave, contrôle final.

## Préparation
- Sortir le préimprégné du congélateur et le laisser revenir à température ambiante dans son emballage fermé, pour éviter la condensation.
- Drapage en salle propre uniquement. Gants nitrile obligatoires, aucun produit siliconé dans la zone.
- Respecter l'ordre et l'orientation des plis donnés par la gamme GAMME-CP210. Compactage sous vide intermédiaire tous les 4 plis.

## Mise sous vide
- Poser tissu d'arrachage, film perforé, feutre de drainage, puis bâche à vide avec mastic d'étanchéité.
- **Test d'étanchéité obligatoire avant cuisson** : tirer au vide, isoler la pompe, relever la chute de vide sur 5 minutes. Si la chute dépasse le seuil affiché sur le poste, rechercher la fuite (détecteur ultrasons) et refaire le test. Ne jamais lancer une cuisson sur une bâche non validée.

## Cuisson
- Cycle autoclave programmé : montée en pression puis palier de cuisson. La température de cuisson doit rester dans la tolérance du tableau ci-dessous.
- L'enregistrement du cycle (température, pression, vide) est joint au dossier de lot.

## Contrôle final
- Épaisseur au micromètre en 5 points (4 coins et centre).
- Taux de porosité par contrôle ultrasons (C-scan) sur toute la surface.
- Toute valeur hors tolérance déclenche une fiche de non-conformité selon PROC-QUA-01.

## Tolérances
<!-- TOLERANCES:START -->
| Caractéristique | Unité | Nominal | Min | Max | Résolution |
|---|---|---|---|---|---|
| epaisseur | mm | 3.20 | 3.05 | 3.35 | 0.01 |
| porosite | pct | — | — | 2.0 | 0.1 |
| temperature_cuisson | degC | 180 | 175 | 185 | 1 |
<!-- TOLERANCES:END -->
