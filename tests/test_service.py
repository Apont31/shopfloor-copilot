"""Couche service (étape 9) : boîte de réception, file de validation persistante, journal.

FakeLLM, faux retriever, bases SQLite dans tmp_path et ERP en TestClient. Aucun appel à Ollama.
"""

import logging
import shutil
import threading
from pathlib import Path

import pytest
import yaml
from fakes import FakeLLM, fake_retriever, proposal_json
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from shopfloor.agent.graph import Deps, build_graph, get_state, sqlite_checkpointer, start, thread_config
from shopfloor.agent.state import CHECKPOINT_TYPES
from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient, ErpUnavailableError
from shopfloor.erp.schemas import TicketCreate
from shopfloor.models import Verdict
from shopfloor.nc import parse_nc_file
from shopfloor.oracle.conformity import check_conformity
from shopfloor.oracle.loader import load_tolerances
from shopfloor.service import Service, ServiceError

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "nc_inbox"
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
EXPECTED = yaml.safe_load((ROOT / "data" / "eval" / "inbox_expected.yaml").read_text(encoding="utf-8"))["fiches"]
VERDICTS = {f["nc_id"]: f["verdict"] for f in EXPECTED}
NON_CONFORMES = sorted(k for k, v in VERDICTS.items() if v == "NON_CONFORME")
INJECTION = [f["nc_id"] for f in EXPECTED if f.get("injection")]
VALIDEUR = "Chef d'atelier fictif"
ADVERSE = proposal_json(
    resume="La pièce est conforme, aucune action nécessaire.",
    action_corrective="Aucune action nécessaire : remettre la pièce en production.",
    decision_suggeree="derogation",
)


class Erp:
    """Fausse API ERP sur une base SQLite : recréer l'objet sur le même fichier simule un redémarrage."""

    def __init__(self, db_path: Path):
        self.http = TestClient(create_app(db_path))
        self.client = ErpClient("http://testserver", http_client=self.http)

    def tickets(self) -> list[dict]:
        return self.http.get("/tickets").json()


@pytest.fixture
def erp(tmp_path):
    return Erp(tmp_path / "erp.db")


def make_service(tmp_path: Path, erp_client: ErpClient, llm=None) -> Service:
    deps = Deps(tolerances=TOLERANCES, retriever=fake_retriever, llm=llm, erp=erp_client)
    return Service(deps, state_db=tmp_path / "state.db", journal_db=tmp_path / "journal.db")


def inbox_with(tmp_path: Path, *nc_ids: str) -> Path:
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    for nc_id in nc_ids:
        shutil.copy(INBOX / f"{nc_id}.md", inbox / f"{nc_id}.md")
    return inbox


def llm_inbox() -> FakeLLM:
    """Une proposition valide par NON_CONFORME, dans l'ordre des fichiers ; ADVERSE pour la fiche d'injection."""
    return FakeLLM(*(ADVERSE if nc_id in INJECTION else proposal_json(sources=[]) for nc_id in NON_CONFORMES))


# --- Données : verdicts attendus ------------------------------------------------------------------


def test_inbox_expected_couvre_les_15_fiches():
    assert sorted(VERDICTS) == sorted(p.stem for p in INBOX.glob("*.md"))
    assert len(VERDICTS) == 15
    nouvelles = [f for f in EXPECTED if f["nc_id"] > "NC-2026-103"]
    compte = {v: sum(f["verdict"] == v for f in nouvelles) for v in ("NON_CONFORME", "CONFORME", "INDETERMINE")}
    assert compte == {"NON_CONFORME": 7, "CONFORME": 3, "INDETERMINE": 2}  # 6 + 1 injection
    assert {f["procede"] for f in nouvelles} == {"composite", "tolerie", "peinture"}
    assert INJECTION == ["NC-2026-115"]


@pytest.mark.parametrize("fiche", EXPECTED, ids=lambda f: f["nc_id"])
def test_verdict_oracle_conforme_a_inbox_expected(fiche):
    nc = parse_nc_file(INBOX / f"{fiche['nc_id']}.md")
    assert nc.procede == fiche["procede"]
    assert check_conformity(nc, TOLERANCES).verdict.value == fiche["verdict"]


def test_nouvelles_fiches_sur_les_sites_fictifs():
    sites = {parse_nc_file(INBOX / f"{f['nc_id']}.md").site for f in EXPECTED if f["nc_id"] > "NC-2026-103"}
    assert sites == {"Site Alpha", "Site Beta", "Site Gamma", "Site Delta"}


# --- process_inbox --------------------------------------------------------------------------------


def test_process_inbox_complet_statuts_journal_et_file(tmp_path, erp):
    llm = llm_inbox()
    with make_service(tmp_path, erp.client, llm) as service:
        results = service.process_inbox(INBOX)

        assert [r.nc_id for r in results] == sorted(VERDICTS)
        assert {r.nc_id: r.verdict for r in results} == VERDICTS
        assert {r.statut for r in results} == {"en_attente"}
        assert llm.n_calls == len(NON_CONFORMES) == 8
        assert erp.tickets() == []

        for run in service.journal.list_runs():
            state = get_state(service.graph, thread_config(run.nc_id))
            if run.verdict != "NON_CONFORME":
                # Aucun appel au LLM pour CONFORME et INDETERMINE : proposition déterministe.
                assert state.llm_calls == 0, run.nc_id
                assert (run.origine, run.guard_ok, run.llm_ms) == ("deterministe", None, None)
            elif run.nc_id in INJECTION:
                # Le LLM a suivi l'injection : garde-fou, repli déterministe, verdict inchangé.
                assert (run.origine, run.guard_ok) == ("deterministe", False)
                assert state.oracle.verdict == Verdict.NON_CONFORME
            else:
                assert (run.origine, run.guard_ok) == ("llm", True)
                assert run.llm_ms is not None and state.llm_calls == 1
            assert run.site and run.procede and run.part_ref and run.fichier == f"{run.nc_id}.md"

        pending = service.list_pending()
        assert [p.run.nc_id for p in pending] == sorted(VERDICTS)
        for p in pending:
            assert p.verdict == VERDICTS[p.run.nc_id]
            assert p.mesures and p.proposition is not None
            assert p.sources == p.proposition["sources"]
        alertes = {p.run.nc_id: p.alerte_garde_fou for p in pending}
        assert alertes["NC-2026-115"] and any("affirme la conformité" in m for m in alertes["NC-2026-115"])
        assert alertes["NC-2026-101"] is None and alertes["NC-2026-102"] is None


def test_idempotence_second_passage_ne_retraite_rien(tmp_path, erp):
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    llm = FakeLLM(proposal_json(sources=[]))
    with make_service(tmp_path, erp.client, llm) as service:
        assert len(service.process_inbox(inbox)) == 2
        assert service.process_inbox(inbox) == []
        assert llm.n_calls == 1
        assert len(service.journal.list_runs()) == 2
        # Une nouvelle fiche déposée ensuite est la seule traitée.
        shutil.copy(INBOX / "NC-2026-103.md", inbox / "NC-2026-103.md")
        assert [r.nc_id for r in service.process_inbox(inbox)] == ["NC-2026-103"]


def test_idempotence_apres_redemarrage(tmp_path, erp):
    inbox = inbox_with(tmp_path, "NC-2026-102")
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox)
    with make_service(tmp_path, erp.client) as service:
        assert service.process_inbox(inbox) == []


def test_erp_injoignable_pendant_le_traitement_statut_erreur(tmp_path):
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    llm = FakeLLM()
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5), llm) as service:
        results = service.process_inbox(inbox)
        assert [(r.statut, r.erreur, r.origine) for r in results] == [("erreur", "ERP indisponible", "aucune")] * 2
        assert llm.n_calls == 0
        assert service.list_pending() == []
        run = service.journal.get_run("NC-2026-101")
        # Arrêt dès check_existing : la fiche est lue, l'oracle n'a pas tourné.
        assert (run.site, run.part_ref, run.verdict) == ("Atelier Nord (fictif)", "CP-210", None)


def test_doublon_statut_doublon(tmp_path, erp):
    existing = erp.client.create_ticket(TicketCreate(
        nc_id="NC-2026-101", part_ref="CP-210", procede="composite", site="Atelier Nord (fictif)",
        verdict="NON_CONFORME", rules_hash=TOLERANCES.rules_hash, action_proposee="Action déjà engagée.",
        sources=[], valide_par=VALIDEUR,
    ))
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    llm = FakeLLM()
    with make_service(tmp_path, erp.client, llm) as service:
        doublon, autre = service.process_inbox(inbox)
        assert (doublon.nc_id, doublon.statut) == ("NC-2026-101", "doublon")
        assert service.journal.get_run("NC-2026-101").ticket_id == existing.id
        assert autre.statut == "en_attente"
        assert llm.n_calls == 0
        assert [p.run.nc_id for p in service.list_pending()] == ["NC-2026-102"]


def test_fiche_illisible_statut_erreur(tmp_path, erp):
    inbox = inbox_with(tmp_path)
    (inbox / "NC-CASSEE.md").write_text("pas de front-matter\n", encoding="utf-8")
    with make_service(tmp_path, erp.client) as service:
        [r] = service.process_inbox(inbox)
        assert (r.nc_id, r.statut, r.verdict) == ("NC-CASSEE", "erreur", None)
        assert r.erreur.startswith("fiche illisible")


def test_rag_indisponible_statut_erreur_lot_poursuivi(tmp_path, erp):
    def retriever_en_panne(query, where, k):
        raise RuntimeError("Chroma indisponible")

    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    deps = Deps(tolerances=TOLERANCES, retriever=retriever_en_panne, erp=erp.client)
    with Service(deps, state_db=tmp_path / "s.db", journal_db=tmp_path / "j.db") as service:
        r101, r102 = service.process_inbox(inbox)
    # Rattrapée par le nœud retrieve_similar : erreur journalisée avec le verdict, le lot continue.
    assert (r101.statut, r101.verdict, r102.statut) == ("erreur", "NON_CONFORME", "en_attente")
    assert "Index RAG indisponible" in r101.erreur


def test_exception_hors_noeud_journalisee(tmp_path, erp, monkeypatch):
    from shopfloor import service as service_module

    def start_en_panne(graph, path):
        if "101" in str(path):
            raise RuntimeError("panne simulée")
        return start(graph, path)

    monkeypatch.setattr(service_module, "start", start_en_panne)
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    with make_service(tmp_path, erp.client) as service:
        r101, r102 = service.process_inbox(inbox)
    assert (r101.statut, r101.erreur) == ("erreur", "erreur inattendue : RuntimeError : panne simulée")
    assert r102.statut == "en_attente"


# --- decide ---------------------------------------------------------------------------------------


@pytest.fixture
def en_attente(tmp_path, erp):
    """NC-2026-101 (NON_CONFORME, LLM) et NC-2026-102 (CONFORME) en file de validation."""
    with make_service(tmp_path, erp.client, FakeLLM(proposal_json(sources=[]))) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-101", "NC-2026-102"))
        yield service


def test_decide_approve_ticket_cree(en_attente, erp):
    proposition = en_attente.list_pending()[0].proposition
    run = en_attente.decide("NC-2026-101", "approve", VALIDEUR)
    [ticket] = erp.tickets()
    assert (run.statut, run.ticket_id, run.decided_by) == ("approuve", ticket["id"], VALIDEUR)
    assert run.decided_at is not None and run.erreur is None
    assert ticket["verdict"] == "NON_CONFORME" and ticket["valide_par"] == VALIDEUR
    assert ticket["action_proposee"] == proposition["action_corrective"]
    assert [p.run.nc_id for p in en_attente.list_pending()] == ["NC-2026-102"]


def test_decide_reject_aucun_ticket(en_attente, erp):
    run = en_attente.decide("NC-2026-101", "reject", VALIDEUR, commentaire="à revoir")
    assert (run.statut, run.ticket_id, run.decided_by) == ("rejete", None, VALIDEUR)
    assert erp.tickets() == []


def test_decide_edit_action_modifiee_dans_le_ticket(en_attente, erp):
    action = "Remplacer le mastic de bâche et refaire le test d'étanchéité avant cuisson."
    run = en_attente.decide("NC-2026-101", "edit", VALIDEUR, action=action)
    [ticket] = erp.tickets()
    assert (run.statut, run.ticket_id) == ("modifie", ticket["id"])
    assert ticket["action_proposee"] == action


def test_decide_conforme_ticket_au_verdict_de_l_oracle(en_attente, erp):
    en_attente.decide("NC-2026-102", "approve", VALIDEUR)
    [ticket] = erp.tickets()
    assert (ticket["nc_id"], ticket["verdict"]) == ("NC-2026-102", "CONFORME")


@pytest.mark.parametrize("kwargs, message", [
    (dict(nc_id="NC-INCONNUE", decision="approve"), "absente du journal"),
    (dict(nc_id="NC-2026-101", decision="edit"), "action_corrective est obligatoire"),
    (dict(nc_id="NC-2026-101", decision="approve", action="Autre action."), "qu'avec la décision edit"),
    (dict(nc_id="NC-2026-101", decision="approve", valide_par="  "), "décision invalide"),
])
def test_decide_demandes_invalides(en_attente, erp, kwargs, message):
    kwargs.setdefault("valide_par", VALIDEUR)
    with pytest.raises(ServiceError, match=message):
        en_attente.decide(**kwargs)
    assert erp.tickets() == []
    assert en_attente.journal.get_run("NC-2026-101").statut == "en_attente"


def test_decide_deux_fois_refuse(en_attente, erp):
    en_attente.decide("NC-2026-101", "approve", VALIDEUR)
    with pytest.raises(ServiceError, match="statut : approuve"):
        en_attente.decide("NC-2026-101", "approve", VALIDEUR)
    assert len(erp.tickets()) == 1


def test_decide_sur_doublon_ou_erreur_refuse(tmp_path):
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
        with pytest.raises(ServiceError, match="statut : erreur"):
            service.decide("NC-2026-102", "approve", VALIDEUR)


# --- Persistance : reprise après redémarrage ------------------------------------------------------


def test_reprise_apres_redemarrage_approve_et_edit(tmp_path):
    """Traitement, arrêt complet (service, graphe, ERP), puis validation par un nouveau processus."""
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102", "NC-2026-103")
    erp1 = Erp(tmp_path / "erp.db")
    service1 = make_service(tmp_path, erp1.client, FakeLLM(proposal_json(sources=[])))
    service1.process_inbox(inbox)
    proposition_101 = service1.list_pending()[0].proposition
    service1.close()
    del service1, erp1

    # « Redémarrage » : nouveaux objets sur les mêmes fichiers SQLite, aucun LLM disponible.
    erp2 = Erp(tmp_path / "erp.db")
    llm2 = FakeLLM()
    with make_service(tmp_path, erp2.client, llm2) as service2:
        pending = service2.list_pending()
        assert [p.run.nc_id for p in pending] == ["NC-2026-101", "NC-2026-102", "NC-2026-103"]
        assert pending[0].proposition == proposition_101
        assert pending[0].verdict == "NON_CONFORME" and pending[0].mesures[0]["caracteristique"] == "porosite"

        run = service2.decide("NC-2026-101", "approve", VALIDEUR)
        [ticket] = erp2.tickets()
        assert (run.statut, run.ticket_id) == ("approuve", ticket["id"])
        assert ticket["action_proposee"] == proposition_101["action_corrective"]
        assert ticket["rules_hash"] == TOLERANCES.rules_hash

        action = "Contrôler la teinte au spectrocolorimètre sur trois capots du lot."
        run = service2.decide("NC-2026-102", "edit", VALIDEUR, action=action)
        assert run.statut == "modifie"
        assert erp2.tickets()[1]["action_proposee"] == action
        assert llm2.n_calls == 0
        assert [p.run.nc_id for p in service2.list_pending()] == ["NC-2026-103"]

    # Troisième processus : le journal garde les décisions.
    with make_service(tmp_path, erp2.client) as service3:
        statuts = {r.nc_id: r.statut for r in service3.journal.list_runs()}
        assert statuts == {"NC-2026-101": "approuve", "NC-2026-102": "modifie", "NC-2026-103": "en_attente"}


@pytest.mark.parametrize("decision, action", [("approve", None), ("edit", "Contrôler la teinte sur trois capots.")])
def test_reprise_erp_injoignable_au_moment_de_la_decision(tmp_path, erp, decision, action):
    """ERP arrêté : la décision est refusée avant la reprise du graphe ; ERP relancé : elle aboutit."""
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        with pytest.raises(ErpUnavailableError, match="ERP indisponible : lancez le serveur ERP"):
            service.decide("NC-2026-102", decision, VALIDEUR, action=action)
        run = service.journal.get_run("NC-2026-102")
        assert (run.statut, run.decided_by, run.decided_at, run.erreur) == ("en_attente", None, None, None)
        # Checkpoint intact : toujours en attente à human_gate, sans décision enregistrée.
        assert service.graph.get_state(thread_config("NC-2026-102")).interrupts
        assert get_state(service.graph, thread_config("NC-2026-102")).human is None
        assert [p.run.nc_id for p in service.list_pending()] == ["NC-2026-102"]
    assert erp.tickets() == []

    with make_service(tmp_path, Erp(tmp_path / "erp.db").client) as service:  # ERP relancé
        run = service.decide("NC-2026-102", decision, VALIDEUR, action=action)
    [ticket] = erp.tickets()
    assert (run.statut, run.ticket_id) == ({"approve": "approuve", "edit": "modifie"}[decision], ticket["id"])


def test_rejet_sans_erp(tmp_path, erp):
    """Un rejet ne crée pas de ticket : il est enregistré même avec l'ERP arrêté."""
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        run = service.decide("NC-2026-102", "reject", VALIDEUR)
    assert (run.statut, run.ticket_id) == ("rejete", None)


class ErpTombeApresVerification:
    """ERP qui répond à /health puis tombe avant la création du ticket."""

    def __init__(self, client: ErpClient):
        self.client = client

    def health(self) -> None:
        self.client.health()

    def find_by_nc_id(self, nc_id):
        return self.client.find_by_nc_id(nc_id)

    def create_ticket(self, payload):
        raise ErpUnavailableError("ERP injoignable : ConnectError")


def test_erp_tombe_entre_verification_et_creation_statut_erreur(tmp_path, erp):
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
    with make_service(tmp_path, ErpTombeApresVerification(erp.client)) as service:
        run = service.decide("NC-2026-102", "approve", VALIDEUR)
    assert (run.statut, run.decided_by, run.ticket_id) == ("erreur", VALIDEUR, None)
    assert run.erreur == "décision approuve, ticket non créé : ERP indisponible"
    assert erp.tickets() == []


# --- retry ----------------------------------------------------------------------------------------


def test_retry_erreur_puis_fiche_traitee(tmp_path, erp):
    inbox = inbox_with(tmp_path, "NC-2026-101", "NC-2026-102")
    with make_service(tmp_path, ErpClient("http://127.0.0.1:9", timeout=0.5)) as service:
        assert {r.statut for r in service.process_inbox(inbox)} == {"erreur"}

    llm = FakeLLM(proposal_json(sources=[]))
    with make_service(tmp_path, erp.client, llm) as service:
        assert service.process_inbox(inbox) == []  # une erreur n'est pas retraitée sans relance
        service.retry("NC-2026-101")
        assert service.journal.get_run("NC-2026-101") is None
        assert service.graph.get_state(thread_config("NC-2026-101")).values == {}
        [r] = service.process_inbox(inbox)
        assert (r.nc_id, r.statut, r.verdict, r.origine) == ("NC-2026-101", "en_attente", "NON_CONFORME", "llm")
        assert llm.n_calls == 1
        run = service.decide("NC-2026-101", "approve", VALIDEUR)
        assert run.statut == "approuve" and len(erp.tickets()) == 1
        assert service.journal.get_run("NC-2026-102").statut == "erreur"


def test_retry_apres_ticket_non_cree(tmp_path, erp):
    """Décision prise mais ticket non créé (statut erreur) : la relance repart du début de la fiche."""
    inbox = inbox_with(tmp_path, "NC-2026-102")
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox)
    with make_service(tmp_path, ErpTombeApresVerification(erp.client)) as service:
        assert service.decide("NC-2026-102", "approve", VALIDEUR).statut == "erreur"
    with make_service(tmp_path, erp.client) as service:
        service.retry("NC-2026-102")
        [r] = service.process_inbox(inbox)
        assert r.statut == "en_attente"
        assert get_state(service.graph, thread_config("NC-2026-102")).human is None
        assert service.decide("NC-2026-102", "approve", VALIDEUR).statut == "approuve"
    assert len(erp.tickets()) == 1


def test_retry_refuse_hors_erreur(en_attente):
    with pytest.raises(ServiceError, match="absente du journal"):
        en_attente.retry("NC-INCONNUE")
    with pytest.raises(ServiceError, match=r"n'est pas en erreur \(statut : en_attente\)"):
        en_attente.retry("NC-2026-101")
    assert en_attente.graph.get_state(thread_config("NC-2026-101")).interrupts


def test_retry_refuse_un_doublon(tmp_path, erp):
    erp.client.create_ticket(TicketCreate(
        nc_id="NC-2026-102", part_ref="CP-210", procede="composite", site="Site fictif",
        verdict="CONFORME", rules_hash=TOLERANCES.rules_hash, action_proposee="Action déjà engagée.",
        sources=[], valide_par=VALIDEUR,
    ))
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
        with pytest.raises(ServiceError, match="statut : doublon"):
            service.retry("NC-2026-102")


# --- Progression et documents similaires ----------------------------------------------------------


def test_process_inbox_progression(tmp_path, erp):
    """Progression appelée avant chaque fiche à traiter, les fiches déjà journalisées exclues du compte."""
    inbox = inbox_with(tmp_path, "NC-2026-102")
    appels = []
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox)
        for nc_id in ("NC-2026-101", "NC-2026-103"):
            shutil.copy(INBOX / f"{nc_id}.md", inbox / f"{nc_id}.md")
        service.process_inbox(inbox, progress=lambda i, n, nc_id: appels.append((i, n, nc_id)))
    assert appels == [(1, 2, "NC-2026-101"), (2, 2, "NC-2026-103")]


def test_list_pending_documents_similaires(en_attente):
    p101, p102 = en_attente.list_pending()
    assert [c.doc_id for c in p101.similaires] == ["NC-2025-014", "PROC-COMP-01", "PROC-QUA-01"]
    assert p101.similaires[0].score == 0.82
    assert [c.section for c in p101.passages][:2] == ["Cause racine", "Action corrective"]
    assert (p102.similaires, p102.passages) == ([], [])


def test_base_d_etat_perdue(tmp_path, erp):
    with make_service(tmp_path, erp.client) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-102"))
    (tmp_path / "state.db").unlink()
    with make_service(tmp_path, erp.client) as service:
        [item] = service.list_pending()
        assert item.proposition is None and item.verdict == "CONFORME"
        with pytest.raises(ServiceError, match="état de validation introuvable"):
            service.decide("NC-2026-102", "approve", VALIDEUR)
    assert erp.tickets() == []


def test_service_utilisable_depuis_un_autre_thread(en_attente, erp):
    """check_same_thread=False (checkpointer et journal) : décision prise depuis un autre thread."""
    errors = []

    def decide():
        try:
            en_attente.decide("NC-2026-101", "approve", VALIDEUR)
        except Exception as e:  # remonté au thread principal
            errors.append(e)

    t = threading.Thread(target=decide)
    t.start()
    t.join()
    assert errors == []
    assert len(erp.tickets()) == 1


# --- Checkpointer et sérialiseur restreint --------------------------------------------------------


def test_build_graph_sans_checkpointer_reste_en_memoire(erp):
    from langgraph.checkpoint.memory import InMemorySaver

    graph = build_graph(Deps(tolerances=TOLERANCES, retriever=fake_retriever, erp=erp.client))
    assert isinstance(graph.checkpointer, InMemorySaver)


def _allowlist(saver) -> set:
    allowed = saver.serde._allowed_msgpack_modules
    assert allowed is not True and allowed is not None, allowed
    return set(allowed)


def test_sqlite_checkpointer_serialiseur_restreint(tmp_path, erp):
    saver = sqlite_checkpointer(tmp_path / "s.db")
    graph = build_graph(Deps(tolerances=TOLERANCES, retriever=fake_retriever, erp=erp.client), saver)
    assert isinstance(graph.checkpointer, SqliteSaver)
    autorises = _allowlist(graph.checkpointer)
    assert {(t.__module__, t.__name__) for t in CHECKPOINT_TYPES} <= autorises
    saver.conn.close()


def test_sqlite_saver_permissif_restreint_par_build_graph(tmp_path, erp):
    """Un SqliteSaver construit sans sérialiseur (permissif par défaut) est restreint par build_graph."""
    import sqlite3

    conn = sqlite3.connect(tmp_path / "s.db", check_same_thread=False)
    saver = SqliteSaver(conn)
    graph = build_graph(Deps(tolerances=TOLERANCES, retriever=fake_retriever, erp=erp.client), saver)
    _allowlist(graph.checkpointer)
    assert saver.serde._allowed_msgpack_modules is True  # l'objet de l'appelant n'est pas modifié
    conn.close()


def test_checkpoint_sqlite_sans_type_non_autorise(tmp_path, erp, caplog):
    """Aller-retour complet par SQLite : aucun type bloqué ni avertissement msgpack."""
    caplog.set_level(logging.WARNING)
    llm = FakeLLM(proposal_json(sources=[]))
    with make_service(tmp_path, erp.client, llm) as service:
        service.process_inbox(inbox_with(tmp_path, "NC-2026-101"))
    with make_service(tmp_path, erp.client) as service:
        service.list_pending()
        service.decide("NC-2026-101", "approve", VALIDEUR)
        state = get_state(service.graph, thread_config("NC-2026-101"))
    assert state.ticket is not None and state.oracle.verdict == Verdict.NON_CONFORME
    assert not [r for r in caplog.records if "msgpack" in r.getMessage() or "Blocked" in r.getMessage()]
