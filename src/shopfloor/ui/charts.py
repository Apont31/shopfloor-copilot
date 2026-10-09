"""Graphiques du pilotage (Altair, fourni avec Streamlit) : barres horizontales fines, valeur au bout de la barre."""

import altair as alt

from shopfloor.ui.style import SERIE, TEXTE, TEXTE_SECONDAIRE


def barres(
    rows: list[dict],
    categorie: str,
    valeur: str,
    *,
    texte: str | None = None,
    couleurs: dict[str, str] | None = None,
) -> alt.LayerChart:
    """Une barre par ligne, dans l'ordre des lignes. texte : colonne affichée au bout de la barre (défaut : valeur).

    couleurs : couleur par catégorie ; sans couleurs, une seule série. Chaque barre est nommée sur l'axe :
    la couleur n'est jamais le seul repère, d'où l'absence de légende.
    """
    color = (
        alt.Color(f"{categorie}:N", scale=alt.Scale(domain=list(couleurs), range=list(couleurs.values())), legend=None)
        if couleurs else alt.value(SERIE)
    )
    base = alt.Chart(alt.Data(values=rows)).encode(
        y=alt.Y(f"{categorie}:N", sort=[r[categorie] for r in rows], title=None,
                axis=alt.Axis(labelLimit=220, labelColor=TEXTE, labelFontSize=13, ticks=False, domain=False)),
        x=alt.X(f"{valeur}:Q", title=None,
                axis=alt.Axis(tickMinStep=1, format="d", labelColor=TEXTE_SECONDAIRE, gridOpacity=0.15, domain=False)),
    )
    tooltip = [
        alt.Tooltip(k, type="quantitative" if isinstance(v, (int, float)) else "nominal")
        for k, v in (rows[0].items() if rows else []) if k != texte
    ]
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.62}).encode(color=color, tooltip=tooltip)
    labels = base.mark_text(align="left", dx=6, color=TEXTE, fontSize=13).encode(
        text=alt.Text(f"{texte or valeur}:N"),
    )
    return (bars + labels).properties(height=max(80, 46 * len(rows)))
