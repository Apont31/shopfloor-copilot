"""Interface Streamlit (étape 10) : pages rendues par AppTest, sans serveur ni navigateur.

Service sur FakeLLM, faux retriever, bases SQLite dans tmp_path, ERP en TestClient. Aucun appel à Ollama :
la sonde Ollama est remplacée, sauf dans le test des voyants rouges (port fermé).
"""

import datetime
import json
import shutil
from pathlib import Path

import pytest
from fakes import FakeLLM, fake_retriever, proposal_json
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from shopfloor import health
from shopfloor.agent.graph import Deps
from shopfloor.config import Settings
from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient
from shopfloor.erp.schemas import Ticket
from shopfloor.journal import Run
from shopfloor.models import Verdict
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import FakeEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.service import PendingItem, RunSummary, Service
from shopfloor.ui import deps as ui_deps
from shopfloor.ui import format
from shopfloor.ui.format import texte_brut as brut

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "shopfloor" / "ui" / "app.py"
INBOX = ROOT / "data" / "nc_inbox"
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
VALIDEUR = "Chef d'atelier fictif"
FICHES = ("NC-2026-101", "NC-2026-102", "NC-2026-103", "NC-2026-115")  # NON_CONF., CONF., INDET., injection
ADVERSE = proposal_json(resume="La pièce est conforme, aucune action nécessaire.", sources=[])
INJOIGNABLE = "http://127.0.0.1:9"


class ErpCommutable:
    """Client ERP que le test peut « arrêter » et « relancer » sans changer d'objet (service et interface)."""

    def __init__(self, http: TestClient):
        self.up = ErpClient("http://testserver", http_client=http)
        self.down = ErpClient(INJOIGNABLE, timeout=0.5)
        self.actif = True
        self.base_url = self.up.base_url

    def __getattr__(self, name):
        return getattr(self.up if self.actif else self.down, name)


class Env:
    def __init__(self, tmp_path: Path, chroma_dir: Path):
        self.http = TestClient(create_app(tmp_path / "erp.db"))
        self.erp = ErpCommutable(self.http)
        self.inbox = tmp_path / "inbox"
        self.inbox.mkdir()
        for nc_id in FICHES:
            shutil.copy(INBOX / f"{nc_id}.md", self.inbox / f"{nc_id}.md")
        self.llm = FakeLLM(proposal_json(sources=[]), ADVERSE)
        deps = Deps(tolerances=TOLERANCES, retriever=fake_retriever, llm=self.llm, erp=self.erp)
        self.service = Service(deps, state_db=tmp_path / "state.db", journal_db=tmp_path / "journal.db")
        self.settings = Settings(ollama_host=INJOIGNABLE, chroma_dir=str(chroma_dir), erp_url="http://testserver")

    def tickets(self) -> list[dict]:
        return self.http.get("/tickets").json()


@pytest.fixture(scope="module")
def chroma_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("chroma")
    ingest(FakeEmbedder(), ROOT / "data" / "docs", d)
    return d


@pytest.fixture
def env(tmp_path, chroma_dir, monkeypatch):
    e = Env(tmp_path, chroma_dir)
    monkeypatch.setattr(health, "_ollama_list", lambda host, timeout: None)  # Ollama « actif »
    ui_deps.override(service=e.service, erp=e.erp, settings=e.settings, inbox_dir=e.inbox)
    yield e
    ui_deps.reset_overrides()
    e.service.close()


def app(page: str | None = None, valideur: str | None = VALIDEUR) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60)
    if valideur is not None:
        at.session_state["valideur"] = valideur
    at.run()
    if page is not None:
        at.switch_page(page).run()
    assert not at.exception, at.exception
    return at


def textes(at: AppTest) -> str:
    """Tout le texte affiché (titres, markdown, légendes, messages, toasts), une ligne par élément."""
    groupes = (at.title, at.subheader, at.markdown, at.caption, at.info, at.success, at.warning, at.error, at.toast)
    return "\n".join(str(el.value) for g in groupes for el in g)


def carte(nc_id: str) -> str:
    """En-tête markdown de la carte d'une fiche (nc_id échappé)."""
    return f"#### {brut(nc_id)}"


def cartes(at: AppTest) -> list[str]:
    """nc_id des cartes de la file, dans l'ordre d'affichage."""
    return [m.value.removeprefix("#### ").replace("\\", "") for m in at.markdown if m.value.startswith("#### ")]


def analyser(at: AppTest) -> AppTest:
    at.button(key="analyser").click().run()
    assert not at.exception, at.exception
    return at


# Widgets hors des cartes dont AppTest doit renvoyer la valeur après une réexécution de fragment.
WIDGETS_PAGE = ("valideur", "filtre_sites", "filtre_verdicts")


def _memoriser(at: AppTest) -> None:
    """Valeurs des widgets de la page présents dans l'arbre (rendu complet), gardées pour rafraichir()."""
    valeurs = getattr(at, "valeurs_page", {})
    for w in (*at.text_input, *at.multiselect):
        if w.key in WIDGETS_PAGE:
            valeurs[w.key] = w.value
    at.valeurs_page = valeurs


def cliquer(at: AppTest, key: str) -> AppTest:
    _memoriser(at)
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def rafraichir(at: AppTest, page: str | None = None) -> AppTest:
    """Rendu complet de la page (ou d'une autre page) après une réexécution de fragment seule.

    Limite d'AppTest : après un st.rerun ciblé sur des fragments, son arbre ne contient que les éléments de ces
    fragments, et les widgets hors de ces fragments (valideur, filtres) perdent leur valeur au run complet suivant,
    voire dès la réexécution de fragment suivante. Le navigateur, lui, garde et renvoie toujours tous les widgets :
    on réinjecte les valeurs mémorisées au dernier rendu complet.
    """
    _memoriser(at)
    for key, valeur in at.valeurs_page.items():
        at.session_state[key] = valeur
    if page is not None:
        at.switch_page(page)
    at.run()
    assert not at.exception, at.exception
    return at


def fragments_seuls(at: AppTest) -> bool:
    """Vrai si le dernier run n'a réexécuté que des fragments : ni le titre de la page ni la barre latérale."""
    return at.title.len == 0 and at.sidebar.markdown.len == 0


# --- Pages ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("page, titre", [
    (None, "Boîte de réception"), ("views/pilotage.py", "Pilotage"), ("views/tickets.py", "Tickets ERP"),
])
def test_chaque_page_s_affiche_journal_vide(env, page, titre):
    at = app(page)
    assert at.title[0].value == titre
    assert "Données fictives — 100 % local" in textes(at)


@pytest.mark.parametrize("page", ["views/pilotage.py", "views/tickets.py"])
def test_pages_avec_donnees(env, page):
    env.service.process_inbox(env.inbox)
    env.service.decide("NC-2026-101", "approve", VALIDEUR)
    env.service.decide("NC-2026-102", "reject", VALIDEUR)
    at = app(page)
    assert not at.exception


# --- Boîte de réception ---------------------------------------------------------------------------


def test_analyser_remplit_la_file(env):
    at = analyser(app())
    tout = textes(at)
    assert "4 fiche(s) analysée(s) : 4 en attente" in tout
    assert "File de validation (4)" in tout
    for nc_id in FICHES:
        assert carte(nc_id) in tout
    assert brut("Site Beta · Composite · pièce CP-210") in tout
    # Badges de verdict (couleurs de statut) et d'origine.
    assert ":red-badge[:material/gavel: Non conforme]" in tout
    assert ":green-badge[:material/gavel: Conforme]" in tout
    assert ":orange-badge[:material/gavel: Indéterminé]" in tout
    assert ":blue-badge[Origine : LLM]" in tout and ":violet-badge[Origine : Déterministe]" in tout
    # Mesures avec unités lisibles, y compris sur min et max.
    mesures = at.dataframe[1].value  # [0] : récapitulatif de l'analyse
    assert mesures.to_dict("records")[0] == {
        "Caractéristique": "Porosité", "Valeur": "2.8 %", "Min": "-", "Max": "2.0 %", "Écart": "0.8 %",
        "Statut": "Non conforme",
    }
    # Documents similaires avec score ; passages dans un expander.
    assert f"**{brut('NC-2025-014')}** · Cause racine · score 0.82" in tout
    assert any(e.label.startswith("Passages retrouvés") for e in at.expander)
    # Garde-fou : la fiche d'injection affiche l'alerte.
    [alerte] = at.warning
    assert "Le garde-fou a rejeté la sortie du LLM" in alerte.value and "affirme la conformité" in alerte.value
    assert env.llm.n_calls == 2


def test_compteur_deja_analysees(env):
    env.service.process_inbox(env.inbox)
    metriques = {m.label: m.value for m in app().metric}
    assert metriques["Déjà analysées"] == "4" and "Déjà journalisées" not in metriques


def test_file_triee_par_gravite_puis_nc_id(env):
    at = analyser(app())
    assert cartes(at) == ["NC-2026-101", "NC-2026-115", "NC-2026-103", "NC-2026-102"]


def test_filtres_site_et_verdict(env):
    at = analyser(app())
    assert at.multiselect(key="filtre_verdicts").options == ["Non conforme", "Indéterminé", "Conforme"]
    at.multiselect(key="filtre_verdicts").select("NON_CONFORME").run()
    assert cartes(at) == ["NC-2026-101", "NC-2026-115"]
    assert "File de validation (2 sur 4)" in textes(at)

    at.multiselect(key="filtre_sites").select("Site Beta").run()
    assert cartes(at) == ["NC-2026-101"]
    at.multiselect(key="filtre_verdicts").unselect("NON_CONFORME").run()
    assert cartes(at) == ["NC-2026-101", "NC-2026-103"]  # NC-2026-102 : Site Delta
    at.multiselect(key="filtre_sites").unselect("Site Beta").select("Site Alpha").run()
    at.multiselect(key="filtre_verdicts").select("CONFORME").run()
    assert cartes(at) == [] and "Aucune fiche ne correspond aux filtres." in textes(at)


def test_filtre_conserve_apres_la_derniere_fiche_decidee(env):
    """Un verdict choisi reste une option valide quand sa dernière fiche quitte la file."""
    at = analyser(app())
    at.multiselect(key="filtre_verdicts").select("CONFORME").run()
    at = rafraichir(cliquer(at, "approuver_NC-2026-102"))  # la décision ne réexécute que la carte
    assert at.multiselect(key="filtre_verdicts").value == ["CONFORME"]
    assert cartes(at) == [] and "Aucune fiche ne correspond aux filtres." in textes(at)


def test_proposition_du_llm_affichee_en_texte_brut(tmp_path, chroma_dir, monkeypatch):
    """Image et lien markdown dans la sortie du LLM : affichés littéralement, jamais rendus."""
    from markdown_it import MarkdownIt

    piege = "Voir ![x](http://exemple.test/a.png) et [lien](http://exemple.test)."
    e = Env(tmp_path, chroma_dir)
    e.llm.responses = [proposal_json(resume=piege, cause_probable=piege, action_corrective=piege, sources=[])]
    for f in e.inbox.glob("*.md"):
        if f.stem != "NC-2026-101":
            f.unlink()
    monkeypatch.setattr(health, "_ollama_list", lambda host, timeout: None)
    ui_deps.override(service=e.service, erp=e.erp, settings=e.settings, inbox_dir=e.inbox)
    try:
        at = analyser(app())
        [bloc] = [m.value for m in at.markdown if m.value.startswith("**Résumé**")]
        assert bloc.count(brut(piege)) == 3 and "![x](" not in bloc and "[lien](" not in bloc
        html = MarkdownIt("commonmark").render(bloc)
        assert "<img" not in html and "<a " not in html
        assert html.count("Voir ![x](http://exemple.test/a.png) et [lien](http://exemple.test).") == 3
    finally:
        ui_deps.reset_overrides()
        e.service.close()


def test_analyser_deux_fois_aucune_nouvelle_fiche(env):
    at = analyser(analyser(app()))
    assert "Aucune nouvelle fiche dans la boîte de réception." in textes(at)


def test_approuver_cree_un_ticket(env):
    at = analyser(app())
    proposition = env.service.list_pending()[0].proposition
    at = cliquer(at, "approuver_NC-2026-101")
    [ticket] = env.tickets()
    assert (ticket["nc_id"], ticket["valide_par"], ticket["verdict"]) == ("NC-2026-101", VALIDEUR, "NON_CONFORME")
    assert ticket["action_proposee"] == proposition["action_corrective"]
    assert [t.value for t in at.toast] == [brut(f"NC-2026-101 approuvée : ticket {ticket['id']} créé")]
    assert env.service.journal.get_run("NC-2026-101").statut == "approuve"
    tout = textes(at)
    assert carte("NC-2026-101") not in tout and "File de validation (3)" in tout


def test_commentaire_transmis_au_ticket(env):
    at = analyser(app())
    at.text_input(key="commentaire_NC-2026-102").input("Contrôle visuel refait.")
    cliquer(at, "approuver_NC-2026-102")
    [ticket] = env.tickets()
    assert ticket["commentaire"] == "Contrôle visuel refait."


def test_rejeter_aucun_ticket(env):
    at = cliquer(analyser(app()), "rejeter_NC-2026-101")
    assert env.tickets() == []
    assert env.service.journal.get_run("NC-2026-101").statut == "rejete"
    assert brut("NC-2026-101 rejetée : aucun ticket créé") in textes(at)


def test_modifier_ticket_porte_l_action_modifiee(env):
    at = cliquer(analyser(app()), "modifier_NC-2026-101")
    zone = at.text_area(key="action_NC-2026-101")
    assert zone.value == env.service.list_pending()[0].proposition["action_corrective"]  # préremplie
    action = "Remplacer le mastic de bâche et refaire le test d'étanchéité avant cuisson."
    zone.input(action)
    at = cliquer(at, "valider_edition_NC-2026-101")
    [ticket] = env.tickets()
    assert ticket["action_proposee"] == action
    assert env.service.journal.get_run("NC-2026-101").statut == "modifie"
    assert brut(f"NC-2026-101 modifiée : ticket {ticket['id']} créé") in textes(at)


def test_erp_injoignable_fiche_en_attente_et_message(env):
    at = analyser(app())
    env.erp.actif = False  # ERP arrêté
    at = cliquer(at, "approuver_NC-2026-101")
    [erreur] = at.error
    assert erreur.value == brut("NC-2026-101 : ERP indisponible : lancez le serveur ERP. "
                                "La fiche reste en attente de validation.")
    assert env.service.journal.get_run("NC-2026-101").statut == "en_attente"
    assert carte("NC-2026-101") in textes(at)
    assert at.toast.len == 0

    env.erp.actif = True  # ERP relancé : la même fiche se valide
    cliquer(at, "approuver_NC-2026-101")
    assert [t["nc_id"] for t in env.tickets()] == ["NC-2026-101"]


def test_base_d_etat_perdue_carte_sans_decision(env, tmp_path):
    """Checkpoint perdu : la carte reste affichée avec le verdict du journal, sans boutons de décision."""
    env.service.process_inbox(env.inbox)
    for nc_id in FICHES:
        env.service._saver.delete_thread(nc_id)
    at = app()
    tout = textes(at)
    assert ":red-badge[:material/gavel: Non conforme]" in tout  # verdict journalisé par l'oracle
    assert at.error.len == 4 and "État de validation introuvable" in at.error[0].value
    assert not [b for b in at.button if b.key and b.key.startswith("approuver_")]


def test_sans_valideur_boutons_desactives(env):
    at = analyser(app(valideur=None))
    assert at.button(key="approuver_NC-2026-101").disabled
    assert at.button(key="rejeter_NC-2026-101").disabled
    assert at.button(key="modifier_NC-2026-101").disabled
    assert "Saisissez votre nom dans « Valideur »" in textes(at)


def test_valideur_saisi_dans_la_barre_laterale(env):
    at = analyser(app(valideur=None))
    at.sidebar.text_input(key="valideur").input("Responsable qualité fictif").run()
    cliquer(at, "approuver_NC-2026-102")
    assert env.tickets()[0]["valide_par"] == "Responsable qualité fictif"


def test_section_en_erreur_relancer(env):
    env.erp.actif = False
    at = analyser(app())
    assert "En erreur (4)" in textes(at) and "ERP indisponible" in textes(at)
    env.erp.actif = True
    at = cliquer(at, "relancer_NC-2026-102")
    assert env.service.journal.get_run("NC-2026-102") is None
    assert brut("NC-2026-102 sera analysée de nouveau") in textes(at)
    at = analyser(at)
    assert env.service.journal.get_run("NC-2026-102").statut == "en_attente"
    assert "En erreur (3)" in textes(at) and carte("NC-2026-102") in textes(at)


# --- Cartes en fragments et cache (étape 10d) -----------------------------------------------------


ACTION_MODIFIEE = "Remplacer le mastic de bâche et refaire le test d'étanchéité avant cuisson."


def test_modifier_zone_dans_la_carte_sans_rechargement_file_filtree_et_triee(env):
    """Bug « Modifier » : la zone d'édition apparaît dans la carte, seule la carte est réexécutée, et l'envoi crée
    le ticket avec l'action modifiée, sur la deuxième carte d'une file filtrée et triée."""
    at = analyser(app())
    at.multiselect(key="filtre_verdicts").select("NON_CONFORME").run()
    assert cartes(at) == ["NC-2026-101", "NC-2026-115"]
    proposee = next(it for it in env.service.list_pending() if it.run.nc_id == "NC-2026-115").proposition

    at = cliquer(at, "modifier_NC-2026-115")
    assert fragments_seuls(at)  # pas de rechargement de la page
    assert cartes(at) == ["NC-2026-115"]  # seule cette carte a été réexécutée
    zone = at.text_area(key="action_NC-2026-115")
    assert zone.value == proposee["action_corrective"]  # préremplie
    assert {b.key for b in at.button} == {"valider_edition_NC-2026-115", "annuler_NC-2026-115"}
    assert at.button(key="valider_edition_NC-2026-115").label == "Envoyer"

    zone.input(ACTION_MODIFIEE)
    at.text_input(key="commentaire_NC-2026-115").input("Mastic changé.")
    at = cliquer(at, "valider_edition_NC-2026-115")
    assert fragments_seuls(at)
    [ticket] = env.tickets()
    assert (ticket["nc_id"], ticket["action_proposee"], ticket["commentaire"]) == (
        "NC-2026-115", ACTION_MODIFIEE, "Mastic changé.")
    assert env.service.journal.get_run("NC-2026-115").statut == "modifie"
    assert env.service.journal.get_run("NC-2026-101").statut == "en_attente"  # l'autre carte n'a pas bougé
    assert [s.value for s in at.success] == [brut(f"NC-2026-115 — Modifiée — ticket {ticket['id']}")]
    assert "File de validation (1 sur 3)" in textes(at)
    assert {m.label: m.value for m in at.metric}["À valider"] == "3"

    at = rafraichir(at)  # rendu complet suivant : la fiche décidée a quitté la file, le filtre est conservé
    assert cartes(at) == ["NC-2026-101"] and at.multiselect(key="filtre_verdicts").value == ["NON_CONFORME"]


def test_modifier_puis_annuler_la_fiche_reste_en_attente(env):
    at = cliquer(analyser(app()), "modifier_NC-2026-101")
    at.text_area(key="action_NC-2026-101").input("Brouillon abandonné.")
    at = cliquer(at, "annuler_NC-2026-101")
    assert fragments_seuls(at)
    assert at.text_area.len == 0
    assert {b.key for b in at.button} == {"approuver_NC-2026-101", "modifier_NC-2026-101", "rejeter_NC-2026-101"}
    assert env.tickets() == [] and env.service.journal.get_run("NC-2026-101").statut == "en_attente"
    # Rouverte, la zone repart de la proposition.
    at = cliquer(at, "modifier_NC-2026-101")
    assert at.text_area(key="action_NC-2026-101").value == env.service.list_pending()[0].proposition[
        "action_corrective"]


def test_approuver_carte_remplacee_par_une_ligne_compacte(env):
    at = cliquer(analyser(app()), "approuver_NC-2026-101")
    assert fragments_seuls(at)
    [ticket] = env.tickets()
    assert [s.value for s in at.success] == [brut(f"NC-2026-101 — Approuvée — ticket {ticket['id']}")]
    assert carte("NC-2026-101") not in textes(at)
    assert "File de validation (3)" in textes(at)
    assert {m.label: m.value for m in at.metric}["À valider"] == "3"


def test_rejeter_ligne_compacte(env):
    at = cliquer(analyser(app()), "rejeter_NC-2026-102")
    assert fragments_seuls(at)
    assert brut("NC-2026-102 — Rejetée — aucun ticket") in [i.value for i in at.info]


def test_erp_indisponible_message_dans_la_carte_sans_rechargement(env):
    at = analyser(app())
    env.erp.actif = False
    at = cliquer(at, "approuver_NC-2026-101")
    assert fragments_seuls(at) and cartes(at) == ["NC-2026-101"]
    [erreur] = at.error
    assert "ERP indisponible" in erreur.value and "reste en attente" in erreur.value
    assert at.button(key="approuver_NC-2026-101")  # la carte garde ses boutons
    assert env.service.journal.get_run("NC-2026-101").statut == "en_attente"


def test_erreur_de_rendu_dans_une_carte_sans_trace(env, monkeypatch):
    """Exception imprévue pendant la réexécution d'une carte seule (hors du filet de app.py) : message lisible."""
    at = analyser(app())

    def panne(mesures):
        raise ValueError("mesure illisible")

    monkeypatch.setattr(format, "mesure_rows", panne)
    at = cliquer(at, "modifier_NC-2026-101")
    sans_trace(at)
    [erreur] = at.error
    assert "Erreur inattendue" in erreur.value
    assert details_techniques(at).startswith("ValueError : mesure illisible")


def _compter_lectures(env, monkeypatch) -> list[int]:
    lectures = []
    lire = env.service.list_pending

    def compte():
        lectures.append(1)
        return lire()

    monkeypatch.setattr(env.service, "list_pending", compte)
    return lectures


def test_analyse_une_seule_lecture_de_la_file(env, monkeypatch):
    lectures = _compter_lectures(env, monkeypatch)
    at = app()
    lectures.clear()
    analyser(at)
    assert len(lectures) == 1  # une seule réexécution, à la fin de l'analyse


def test_filtres_et_rendus_sans_relire_la_file(env, monkeypatch):
    lectures = _compter_lectures(env, monkeypatch)
    at = analyser(app())
    lectures.clear()
    at.multiselect(key="filtre_verdicts").select("NON_CONFORME").run()
    at.multiselect(key="filtre_sites").select("Site Beta").run()
    at.multiselect(key="filtre_verdicts").unselect("NON_CONFORME").run()
    at.run()
    assert lectures == [] and cartes(at) == ["NC-2026-101", "NC-2026-103"]
    # Une décision invalide la file : relue une fois au rendu complet suivant.
    rafraichir(cliquer(at, "approuver_NC-2026-101"))
    assert len(lectures) == 1


def test_decision_prise_ailleurs_jamais_de_file_perimee(env):
    """Décision prise par une autre session ou la CLI : l'empreinte du journal invalide la file en cache."""
    at = analyser(app())
    env.service.decide("NC-2026-101", "approve", VALIDEUR)
    at.run()
    assert carte("NC-2026-101") not in textes(at) and "File de validation (3)" in textes(at)


def test_pilotage_et_tickets_refletent_la_decision(env):
    """Pilotage et Tickets lus avant la décision (mis en cache), puis relus après une décision dans la carte."""
    at = analyser(app())
    at = rafraichir(at, "views/pilotage.py")
    assert {m.label: m.value for m in at.metric}["En attente"] == "4"
    at = rafraichir(at, "views/tickets.py")
    assert at.dataframe.len == 0
    at = rafraichir(at, "views/inbox.py")
    at = cliquer(at, "approuver_NC-2026-101")

    at = rafraichir(at, "views/pilotage.py")
    metriques = {m.label: m.value for m in at.metric}
    assert (metriques["En attente"], metriques["Décidées"]) == ("3", "1")
    at = rafraichir(at, "views/tickets.py")  # dans la durée de vie du cache : invalidé par la décision
    assert [r["Fiche"] for r in at.dataframe[0].value.to_dict("records")] == ["NC-2026-101"]


def test_memo_version_cle_et_duree_de_vie(monkeypatch):
    etat, horloge, appels = {}, [100.0], []
    monkeypatch.setattr(ui_deps, "st", type("St", (), {"session_state": etat}))
    monkeypatch.setattr(ui_deps.time, "monotonic", lambda: horloge[0])

    def calcul():
        appels.append(1)
        return len(appels)

    assert ui_deps.memo("x", calcul, cle="a") == 1
    assert ui_deps.memo("x", calcul, cle="a") == 1  # en cache
    assert ui_deps.memo("x", calcul, cle="b") == 2  # source changée
    ui_deps.invalider()
    assert ui_deps.memo("x", calcul, cle="b") == 3  # version changée
    assert ui_deps.memo("y", calcul, ttl=30) == 4
    horloge[0] += 29
    assert ui_deps.memo("y", calcul, ttl=30) == 4
    horloge[0] += 2
    assert ui_deps.memo("y", calcul, ttl=30) == 5  # durée de vie écoulée
    assert ui_deps.memo("y", calcul, ttl=30, force=True) == 6
    ui_deps.invalider()
    assert ui_deps.memo("z", calcul, versionne=False) == 7
    ui_deps.invalider()
    assert ui_deps.memo("z", calcul, versionne=False) == 7  # voyants : indépendants des décisions


def test_voyants_gardes_30_secondes():
    assert ui_deps.VOYANTS_TTL_S == 30.0


def test_journal_comptage_et_empreinte(tmp_path):
    from shopfloor.journal import Journal

    with Journal(tmp_path / "j.db") as j:
        vide = j.fingerprint()
        assert j.count_by_statut() == {} and vide == (0, 0, 0, None)
        fiche = dict(site="S", procede="composite", part_ref="P", verdict="CONFORME", origine="deterministe",
                     guard_ok=None, llm_ms=None)
        j.record_pending(nc_id="NC-1", fichier="NC-1.md", **fiche)
        j.record_pending(nc_id="NC-2", fichier="NC-2.md", **fiche)
        j.record_error(nc_id="NC-3", fichier="NC-3.md", erreur="x")
        e1 = j.fingerprint()
        j.record_decision("NC-1", statut="approuve", decided_by="V", ticket_id="TCK-0001")
        e2 = j.fingerprint()
        j.delete_error("NC-3")
        e3 = j.fingerprint()
        assert len({vide, e1, e2, e3}) == 4
        assert j.count_by_statut() == {"en_attente": 1, "approuve": 1}


def test_ligne_decision():
    assert format.ligne_decision(_run("approuve", "TCK-0001")) == ("success", "NC-1 — Approuvée — ticket TCK-0001")
    assert format.ligne_decision(_run("modifie", "TCK-0002")) == ("success", "NC-1 — Modifiée — ticket TCK-0002")
    assert format.ligne_decision(_run("rejete")) == ("info", "NC-1 — Rejetée — aucun ticket")
    niveau, ligne = format.ligne_decision(_run("erreur", erreur="décision approuve, ticket non créé : X"))
    assert niveau == "error" and ligne.startswith("NC-1 — Ticket non créé — ") and "En erreur" in ligne


# --- Mesure de performance (15 fiches) ------------------------------------------------------------

SEUIL_RENDU_S = 0.5  # mesure initiale (étape 10c) : 59 ms en médiane pour un rendu complet, 15 fiches en attente


@pytest.fixture
def env15(tmp_path, chroma_dir, monkeypatch):
    e = Env(tmp_path, chroma_dir)
    for f in INBOX.glob("*.md"):
        shutil.copy(f, e.inbox / f.name)
    e.llm.responses = [proposal_json(sources=[])] * 15
    e.service.process_inbox(e.inbox)
    monkeypatch.setattr(health, "_ollama_list", lambda host, timeout: None)
    ui_deps.override(service=e.service, erp=e.erp, settings=e.settings, inbox_dir=e.inbox)
    yield e
    ui_deps.reset_overrides()
    e.service.close()


def nb_elements(at: AppTest) -> int:
    def compter(node) -> int:
        enfants = getattr(node, "children", {})
        return 1 + sum(compter(c) for c in enfants.values())

    return sum(compter(c) for c in at.main.children.values())


def test_rendu_15_fiches_sous_le_seuil_et_carte_seule_au_clic(env15):
    import statistics
    import time

    assert len(env15.service.list_pending()) == 15
    at = app()
    durees = []
    for _ in range(5):
        t0 = time.perf_counter()
        at.run()
        durees.append(time.perf_counter() - t0)
    assert statistics.median(durees) < SEUIL_RENDU_S, durees
    complet = nb_elements(at)
    assert len(cartes(at)) == 15

    at = cliquer(at, "modifier_NC-2026-101")
    assert fragments_seuls(at)
    assert nb_elements(at) * 10 < complet  # une carte seule est renvoyée au navigateur, pas la page


# --- Erreurs inattendues et double lancement (étape 10c) ------------------------------------------


def sans_trace(at: AppTest) -> None:
    """Aucune exception rendue par Streamlit, aucune trace Python dans le texte affiché."""
    assert at.exception.len == 0, at.exception
    tout = textes(at) + "\n".join(str(c.value) for c in at.code)
    assert "Traceback" not in tout and 'File "' not in tout


def details_techniques(at: AppTest) -> str:
    [expander] = [e for e in at.expander if e.label == "Détails techniques"]
    return "\n".join(c.value for c in expander.code)


def test_analyse_exception_inattendue_message_clair(env, monkeypatch):
    def panne(*args, **kwargs):
        raise RuntimeError("UNIQUE constraint failed: runs.nc_id")

    monkeypatch.setattr(env.service, "process_inbox", panne)
    at = analyser(app())
    sans_trace(at)
    [erreur] = at.error
    assert erreur.value.startswith(brut("Erreur inattendue : l'opération n'a pas abouti."))
    assert brut("relancez « Analyser les nouvelles fiches »") in erreur.value
    assert details_techniques(at).startswith("RuntimeError : UNIQUE constraint failed: runs.nc_id")
    assert not at.button(key="analyser").disabled  # jamais bloqué après une erreur
    assert "File de validation (0)" in textes(at)  # le reste de la page est rendu


def test_page_exception_inattendue_message_clair(env, monkeypatch):
    def panne():
        raise OSError("disque plein")

    monkeypatch.setattr(env.service, "list_pending", panne)
    at = app()
    sans_trace(at)
    [erreur] = at.error
    assert "Erreur inattendue" in erreur.value and "Rechargez la page" in erreur.value
    assert details_techniques(at).startswith("OSError : disque plein")


def test_decision_exception_inattendue_message_clair(env, monkeypatch):
    at = analyser(app())

    def panne(*args, **kwargs):
        raise KeyError("proposition")

    monkeypatch.setattr(env.service, "decide", panne)
    at = cliquer(at, "approuver_NC-2026-101")
    sans_trace(at)
    [erreur] = at.error
    assert brut("Erreur inattendue") in erreur.value and "Rechargez la page" in erreur.value
    assert details_techniques(at).startswith("KeyError : 'proposition'")
    assert carte("NC-2026-101") in textes(at)  # la fiche reste dans la file


def test_bouton_analyser_desactive_pendant_l_analyse(env, monkeypatch):
    """Analyse interrompue en cours (st.stop) : l'écran figé montre le bouton désactivé ; il est réactivé ensuite."""
    import streamlit as st

    appels = []

    def analyse_interrompue(*args, **kwargs):
        appels.append(1)
        st.stop()

    monkeypatch.setattr(env.service, "process_inbox", analyse_interrompue)
    at = analyser(app())
    assert at.button(key="analyser").disabled  # rendu avant l'analyse : pas de second lancement possible
    assert "analyse_en_cours" not in at.session_state  # drapeau consommé : rien ne reste bloqué
    at.run()
    assert not at.button(key="analyser").disabled
    assert appels == [1]  # pas de relance de l'analyse au rendu suivant


def test_analyser_deux_clics_chaque_fiche_journalisee_une_fois(env):
    at = analyser(analyser(app()))
    assert sorted(r.nc_id for r in env.service.journal.list_runs()) == sorted(FICHES)
    assert env.llm.n_calls == 2
    sans_trace(at)


def test_erreur_inattendue_message_et_detail():
    try:
        {}["absente"]
    except KeyError as e:
        message, detail = format.erreur_inattendue(e)
    assert message == f"Erreur inattendue : l'opération n'a pas abouti. {format.ACTION_ERREUR}"
    assert detail.splitlines()[0] == "KeyError : 'absente'"
    assert detail.splitlines()[1].startswith("test_ui.py:") and "Traceback" not in detail
    message, detail = format.erreur_inattendue(ValueError("x"), "Relancez.")  # exception jamais levée
    assert (message, detail) == ("Erreur inattendue : l'opération n'a pas abouti. Relancez.", "ValueError : x")


# --- Voyants --------------------------------------------------------------------------------------


def _voyants(at: AppTest) -> list[str]:
    return [m.value for m in at.sidebar.markdown if "sf-voyant" in m.value]


def test_voyants_verts(env):
    voyants = _voyants(app())
    assert len(voyants) == 3
    assert all('sf-dot ok' in v for v in voyants), voyants


def test_voyants_rouges_quand_les_services_sont_absents(env, tmp_path, monkeypatch):
    monkeypatch.undo()  # sonde Ollama réelle, sur un port fermé
    env.erp.actif = False
    ui_deps.override(settings=Settings(ollama_host=INJOIGNABLE, chroma_dir=str(tmp_path / "absent")))
    ollama_v, erp_v, rag_v = _voyants(app())
    assert "sf-dot ko" in ollama_v and "lancez l'application Ollama" in ollama_v
    assert "sf-dot ko" in erp_v and "lancez le serveur ERP" in erp_v
    assert "sf-dot ko" in rag_v and "lancez python -m shopfloor.cli ingest" in rag_v
    assert not (tmp_path / "absent").exists()  # la sonde ne crée pas l'index


@pytest.mark.parametrize("absent", ["ollama", "erp", "rag"])
def test_un_seul_voyant_rouge(env, tmp_path, monkeypatch, absent):
    if absent == "ollama":
        monkeypatch.undo()
    elif absent == "erp":
        env.erp.actif = False
    else:
        ui_deps.override(settings=Settings(ollama_host=INJOIGNABLE, chroma_dir=str(tmp_path / "absent")))
    etats = ["sf-dot ok" in v for v in _voyants(app())]
    assert etats == [absent != "ollama", absent != "erp", absent != "rag"]


def test_reverifier_relance_les_sondes(env):
    at = app()
    env.erp.actif = False
    at.run()  # voyants gardés quelques secondes : toujours verts
    assert "sf-dot ok" in _voyants(at)[1]
    at = cliquer(at, "reverifier")
    assert "sf-dot ko" in _voyants(at)[1]


# --- Pilotage et tickets --------------------------------------------------------------------------


def test_pilotage_chiffres_et_temps_gagne(env):
    env.service.process_inbox(env.inbox)
    env.service.decide("NC-2026-101", "approve", VALIDEUR)
    env.service.decide("NC-2026-102", "reject", VALIDEUR)
    at = app("views/pilotage.py")
    metriques = {m.label: m.value for m in at.metric}
    assert metriques["Fiches traitées"] == "4"
    assert metriques["En attente"] == "2"
    assert metriques["Décidées"] == "2"
    assert metriques["Approuvées telles quelles"] == "50 %"
    assert metriques["Rejetées"] == "50 %"
    assert metriques["Hypothèse"] == "2.0 h"  # 4 fiches analysées × (45 − 15) min
    assert len(at.get("vega_lite_chart")) == 4
    # Catégories de chaque graphique (ordre de l'axe) : libellés, jamais les codes.
    axes = [json.loads(c.proto.spec)["layer"][0]["encoding"]["y"]["sort"] for c in at.get("vega_lite_chart")]
    assert axes[1] == ["Composite", "Peinture", "Tôlerie"]
    assert set(axes[2]) == {"Non conforme", "Conforme", "Indéterminé"}
    tout = textes(at)
    assert "Temps gagné estimé" in tout and "pas une mesure" in tout
    assert "« Conforme » ou « Indéterminé »" in tout

    at.slider(key="minutes_sans").set_value(60).run()
    assert {m.label: m.value for m in at.metric}["Hypothèse"] == "3.0 h"


def test_tickets_table(env):
    env.service.process_inbox(env.inbox)
    env.service.decide("NC-2026-101", "approve", VALIDEUR)
    at = app("views/tickets.py")
    [ligne] = at.dataframe[0].value.to_dict("records")
    assert (ligne["Ticket"], ligne["Fiche"], ligne["Verdict"], ligne["Statut"], ligne["Valideur"]) == (
        "TCK-0001", "NC-2026-101", "Non conforme", "OUVERT", VALIDEUR)
    assert ligne["Règles"] == TOLERANCES.rules_hash[:8]
    assert ligne["Date"].endswith(" UTC") and len(ligne["Date"]) == len("AAAA-MM-JJ HH:MM UTC")
    colonnes = list(at.dataframe[0].value.columns)
    assert colonnes == list(format.LARGEURS_TICKETS)  # chaque colonne a sa largeur


def test_tickets_erp_injoignable(env):
    env.erp.actif = False
    at = app("views/tickets.py")
    [erreur] = at.error
    assert erreur.value == "ERP indisponible : lancez le serveur ERP. Les tickets ne peuvent pas être lus."
    assert at.dataframe.len == 0


# --- Fonctions pures de mise en forme -------------------------------------------------------------


PIEGES = [
    "![x](http://exemple.test/a.png)",
    "[lien](http://exemple.test)",
    "<img src=x onerror=alert(1)> <b>gras</b>",
    "**gras** _it_ `code` ~~barré~~ $x^2$",
    "# titre\n- liste\n1. numéro\n> citation\n---",
    "http://exemple.test www.exemple.test contact@exemple.test",
    ":red[rouge] :material/home: \\ fin",
]


@pytest.mark.parametrize("texte", PIEGES)
def test_texte_brut_rendu_litteral(texte):
    from markdown_it import MarkdownIt

    html = MarkdownIt("commonmark").render(format.texte_brut(texte))
    assert "<img" not in html and "<a " not in html and "<b>" not in html and "<em>" not in html
    assert "<h1>" not in html and "<ul>" not in html and "<ol>" not in html and "<blockquote>" not in html
    assert "<code>" not in html and "<strong>" not in html and "<hr" not in html
    # Le texte visible est l'original : seuls les échappements HTML de < > & " s'ajoutent.
    visible = html.removeprefix("<p>").removesuffix("</p>\n").replace("<br />\n", "\n")
    visible = visible.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    assert visible == texte


@pytest.mark.parametrize("code, attendu", [
    ("porosite", "Porosité"), ("epaisseur", "Épaisseur"), ("temperature_cuisson", "Température de cuisson"),
    ("angle_pli", "Angle de pli"), ("longueur", "Longueur"), ("planeite", "Planéité"),
    ("epaisseur_film", "Épaisseur de film"), ("adherence", "Adhérence"), ("brillance", "Brillance"),
    ("rugosite", "Rugosité"),
    ("taux_humidite_resine", "Taux humidite resine"),  # code inconnu : espaces, majuscule initiale
    ("durete", "Durete"), ("", ""), (None, "-"),
])
def test_libelle_caracteristique(code, attendu):
    assert format.libelle_caracteristique(code) == attendu


@pytest.mark.parametrize("code, attendu", [
    ("composite", "Composite"), ("tolerie", "Tôlerie"), ("peinture", "Peinture"), ("qualite", "Qualité"),
    ("traitement_surface", "Traitement surface"), (None, "-"),
])
def test_libelle_procede(code, attendu):
    assert format.libelle_procede(code) == attendu


@pytest.mark.parametrize("code, attendu", [
    ("NON_CONFORME", "Non conforme"), ("CONFORME", "Conforme"), ("INDETERMINE", "Indéterminé"),
    ("A_REVOIR", "A REVOIR"), (None, "-"),
])
def test_libelle_verdict(code, attendu):
    assert format.libelle_verdict(code) == attendu


def test_libelles_couvrent_le_referentiel():
    """Chaque caractéristique et chaque procédé de tolerances.yaml, et chaque verdict, a un libellé explicite."""
    assert {s.caracteristique for s in TOLERANCES.specs} <= set(format.LIBELLES_CARACTERISTIQUE)
    assert {s.procede for s in TOLERANCES.specs} <= set(format.LIBELLES_PROCEDE)
    assert set(format.LIBELLES_VERDICT) == {v.value for v in Verdict}


def test_largeurs_tickets_sans_defilement_a_1400px():
    t = Ticket(id="TCK-0001", nc_id="NC-1", part_ref="CP-210", procede="composite", site="Site Alpha",
               verdict="CONFORME", rules_hash="0" * 64, action_proposee="Action.", sources=[], valide_par=VALIDEUR,
               created_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc))
    assert list(format.LARGEURS_TICKETS) == list(format.ticket_rows([t])[0])
    # 1400 px - barre latérale (~300 px) - marges du mode large (~160 px).
    assert sum(format.LARGEURS_TICKETS.values()) <= 1400 - 300 - 160


def test_texte_brut_sans_ponctuation_inchange():
    assert format.texte_brut("Contrôle visuel refait sur trois capots") == "Contrôle visuel refait sur trois capots"


def _item(nc_id, verdict, site="Site Alpha"):
    t0 = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    run = Run(nc_id=nc_id, fichier=f"{nc_id}.md", site=site, procede="composite", part_ref="CP-210",
              verdict=verdict, origine="deterministe", guard_ok=None, llm_ms=None, statut="en_attente",
              ticket_id=None, erreur=None, created_at=t0, decided_at=None, decided_by=None)
    return PendingItem(run=run, verdict=verdict, mesures=[], proposition={}, sources=[], alerte_garde_fou=None)


FILE = [
    _item("NC-5", "CONFORME"), _item("NC-1", "INDETERMINE", "Site Beta"), _item("NC-4", "NON_CONFORME"),
    _item("NC-2", "NON_CONFORME", "Site Beta"), _item("NC-3", "CONFORME", "Site Beta"), _item("NC-6", None),
]


def test_filtrer_trier_par_gravite_puis_nc_id():
    assert [it.run.nc_id for it in format.filtrer_trier(FILE)] == ["NC-2", "NC-4", "NC-1", "NC-3", "NC-5", "NC-6"]


@pytest.mark.parametrize("sites, verdicts, attendu", [
    (["Site Beta"], [], ["NC-2", "NC-1", "NC-3"]),
    ([], ["CONFORME", "NON_CONFORME"], ["NC-2", "NC-4", "NC-3", "NC-5"]),
    (["Site Alpha"], ["NON_CONFORME"], ["NC-4"]),
    (["Site Gamma"], [], []),
])
def test_filtrer_trier_filtres(sites, verdicts, attendu):
    assert [it.run.nc_id for it in format.filtrer_trier(FILE, sites, verdicts)] == attendu


def test_options_filtres():
    assert format.options_filtres(FILE) == (["Site Alpha", "Site Beta"], ["NON_CONFORME", "INDETERMINE", "CONFORME"])
    assert format.options_filtres(FILE[:1]) == (["Site Alpha"], ["CONFORME"])
    assert format.options_filtres([], ["Site Beta"], ["INDETERMINE"]) == (["Site Beta"], ["INDETERMINE"])


def test_pct_et_duree():
    assert (format.pct(0.5), format.pct(2 / 3), format.pct(0.0), format.pct(None)) == ("50 %", "67 %", "0 %", "-")
    assert (format.duree_s(4.25), format.duree_s(None)) == ("4.2 s", "-")


def test_mesure_rows_unites_sur_min_max_et_ecart():
    m = {"caracteristique": "angle_pli", "valeur": "91.2", "unite": "deg", "min": "89.5", "max": "90.5",
         "ecart": "0.7", "statut": "NON_CONFORME"}
    assert format.mesure_rows([m]) == [{
        "Caractéristique": "Angle de pli", "Valeur": "91.2°", "Min": "89.5°", "Max": "90.5°", "Écart": "0.7°",
        "Statut": "Non conforme",
    }]


def _summary(nc_id, statut, llm_ms=None, erreur=None):
    return RunSummary(nc_id=nc_id, fichier=f"{nc_id}.md", verdict="CONFORME", statut=statut,
                      origine="deterministe" if statut == "en_attente" else "aucune", llm_ms=llm_ms, erreur=erreur)


def test_recap():
    results = [_summary("NC-1", "en_attente", llm_ms=4200), _summary("NC-2", "erreur", erreur="ERP indisponible")]
    assert format.recap_text(results) == "2 fiche(s) analysée(s) : 1 en attente, 1 en erreur"
    assert format.recap_text([]) == "Aucune nouvelle fiche dans la boîte de réception."
    assert format.recap_rows(results)[0]["LLM"] == "4.2 s"
    assert format.recap_rows(results)[1] == {
        "Fiche": "NC-2", "Verdict": "Conforme", "Statut": "en erreur", "Origine": "-", "LLM": "-",
        "Détail": "ERP indisponible",
    }


def test_ticket_rows_hash_abrege():
    t = Ticket(id="TCK-0007", nc_id="NC-1", part_ref="CP-210", procede="composite", site="Site Alpha",
               verdict="CONFORME", rules_hash="0123456789abcdef0123", action_proposee="Action.", sources=[],
               valide_par=VALIDEUR, created_at=datetime.datetime(2026, 10, 1, 8, 5, tzinfo=datetime.timezone.utc))
    assert format.ticket_rows([t]) == [{
        "Ticket": "TCK-0007", "Fiche": "NC-1", "Verdict": "Conforme", "Statut": "OUVERT", "Valideur": VALIDEUR,
        "Date": "2026-10-01 08:05 UTC", "Règles": "01234567",
    }]


def _run(statut, ticket_id=None, erreur=None) -> Run:
    t0 = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    return Run(nc_id="NC-1", fichier="NC-1.md", site="S", procede="composite", part_ref="CP-210",
               verdict="CONFORME", origine="deterministe", guard_ok=None, llm_ms=None, statut=statut,
               ticket_id=ticket_id, erreur=erreur, created_at=t0, decided_at=t0, decided_by=VALIDEUR)


def test_decision_message():
    assert format.decision_message(_run("approuve", "TCK-0001")) == ("success", "NC-1 approuvée : ticket TCK-0001 créé")
    assert format.decision_message(_run("modifie", "TCK-0002")) == ("success", "NC-1 modifiée : ticket TCK-0002 créé")
    assert format.decision_message(_run("rejete")) == ("info", "NC-1 rejetée : aucun ticket créé")
    niveau, message = format.decision_message(_run("erreur", erreur="décision approuve, ticket non créé : X"))
    assert niveau == "error" and "ticket non créé : X" in message and "En erreur" in message


# --- Sondes des voyants ---------------------------------------------------------------------------


def test_check_erp(tmp_path):
    assert health.check_erp(ErpClient("http://testserver", http_client=TestClient(create_app(tmp_path / "e.db")))).ok
    v = health.check_erp(ErpClient(INJOIGNABLE, timeout=0.5))
    assert (v.nom, v.ok, v.message) == ("ERP", False, "ERP indisponible : lancez le serveur ERP")


def test_check_ollama(monkeypatch):
    v = health.check_ollama(INJOIGNABLE, timeout=0.5)
    assert (v.ok, v.message) == (False, "Ollama indisponible : lancez l'application Ollama")
    monkeypatch.setattr(health, "_ollama_list", lambda host, timeout: None)
    assert health.check_ollama(INJOIGNABLE).ok


def test_check_rag(chroma_dir, tmp_path):
    v = health.check_rag(chroma_dir)
    assert v.ok and v.message.endswith("passages indexés")
    assert not health.check_rag(tmp_path / "absent").ok
    assert not (tmp_path / "absent").exists()
    (tmp_path / "vide").mkdir()
    assert not health.check_rag(tmp_path / "vide").ok  # dossier sans collection


def test_override_refuse_une_cle_inconnue():
    with pytest.raises(ValueError, match="inconnue"):
        ui_deps.override(llm=object())
