"""Apparence de l'interface : couleurs et seul CSS injecté de l'application.

Thème « atelier » (fond graphite, accent ambre) dans .streamlit/config.toml ; ce module n'ajoute que les voyants,
le bandeau et quelques réglages de lisibilité.
"""

from html import escape

import streamlit as st

TEXTE = "#E8E6E1"
TEXTE_SECONDAIRE = "#9BA1A9"
AMBRE = "#FFB000"

# Statuts : réservés aux verdicts et aux voyants, toujours accompagnés d'un libellé.
ROUGE, VERT, AMBRE_STATUT = "#E5484D", "#30A46C", "#E2A336"
COULEURS_VERDICT = {"NON_CONFORME": ROUGE, "CONFORME": VERT, "INDETERMINE": AMBRE_STATUT}
BADGE_VERDICT = {"NON_CONFORME": "red", "CONFORME": "green", "INDETERMINE": "orange"}
LIBELLE_VERDICT = {"NON_CONFORME": "NON CONFORME", "CONFORME": "CONFORME", "INDETERMINE": "INDÉTERMINÉ"}

# Séries des graphiques (hors statuts) : paire validée daltonisme et contraste sur le fond graphite.
SERIE = "#3987E5"
COULEURS_ORIGINE = {"LLM": "#3987E5", "Déterministe": "#D55181"}
BADGE_ORIGINE = {"llm": ("LLM", "blue"), "deterministe": ("Déterministe", "violet")}

_CSS = f"""
<style>
.sf-voyant {{ display: flex; gap: .6rem; align-items: flex-start; margin: .45rem 0; line-height: 1.25; }}
.sf-dot {{ width: .75rem; height: .75rem; border-radius: 50%; margin-top: .25rem; flex: none; }}
.sf-dot.ok {{ background: {VERT}; box-shadow: 0 0 6px {VERT}99; }}
.sf-dot.ko {{ background: {ROUGE}; box-shadow: 0 0 6px {ROUGE}99; }}
.sf-voyant b {{ font-weight: 600; }}
.sf-voyant small {{ display: block; color: {TEXTE_SECONDAIRE}; font-size: .8rem; }}
.sf-bandeau {{ border: 1px solid {AMBRE}66; background: {AMBRE}1A; color: {AMBRE}; padding: .45rem .7rem;
  border-radius: .5rem; font-weight: 600; text-align: center; letter-spacing: .03em; }}
.sf-label {{ color: {TEXTE_SECONDAIRE}; font-size: .78rem; text-transform: uppercase; letter-spacing: .07em;
  margin: .6rem 0 .15rem; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ margin-bottom: .6rem; }}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def voyant_html(nom: str, ok: bool, message: str) -> str:
    etat, libelle = ("ok", "actif") if ok else ("ko", "absent")
    return (f'<div class="sf-voyant"><span class="sf-dot {etat}"></span><span><b>{escape(nom, quote=False)}</b> : '
            f'{libelle}<small>{escape(message, quote=False)}</small></span></div>')


def bandeau_html(texte: str) -> str:
    return f'<div class="sf-bandeau">{escape(texte, quote=False)}</div>'


def label_html(texte: str) -> str:
    return f'<div class="sf-label">{escape(texte, quote=False)}</div>'
