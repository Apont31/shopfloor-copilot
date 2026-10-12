"""Page « Assistant procédures » rendue par AppTest : FakeLLM, faux retriever, aucun Ollama."""

from pathlib import Path

import pytest
from fakes import CHUNKS, FakeLLM, FakeRetriever
from streamlit.testing.v1 import AppTest
from test_assistant import reponse_json

from shopfloor import health
from shopfloor.assistant import PAS_FIABLE, REFUS, AssistantDeps
from shopfloor.config import Settings
from shopfloor.erp.client import ErpClient
from shopfloor.errors import RAG_INDISPONIBLE
from shopfloor.oracle.loader import load_tolerances
from shopfloor.ui import deps as ui_deps
from shopfloor.ui.format import texte_brut as brut

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "shopfloor" / "ui" / "app.py"
PAGE = "views/assistant.py"
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
INJOIGNABLE = "http://127.0.0.1:9"
QUESTION = "Que s'est-il passé sur la bâche à vide ?"


@pytest.fixture
def installer(tmp_path, monkeypatch):
    """installer(llm, retriever) : dépendances de la page ; voyants sur des services injoignables, Ollama « actif »."""
    monkeypatch.setattr(health, "_ollama_list", lambda host, timeout: None)

    def _installer(llm=None, retriever=None):
        ui_deps.override(
            assistant=AssistantDeps(tolerances=TOLERANCES, retriever=retriever or FakeRetriever(), llm=llm),
            settings=Settings(ollama_host=INJOIGNABLE, chroma_dir=str(tmp_path / "chroma"), erp_url=INJOIGNABLE),
            erp=ErpClient(INJOIGNABLE, timeout=0.5),
        )

    yield _installer
    ui_deps.reset_overrides()


def page() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    at.switch_page(PAGE).run()
    assert not at.exception, at.exception
    return at


def poser(at: AppTest, question: str) -> AppTest:
    at.chat_input(key="question_assistant").set_value(question).run()
    assert not at.exception, at.exception
    return at


def textes(at: AppTest) -> str:
    groupes = (at.title, at.markdown, at.caption, at.info, at.warning, at.error)
    return "\n".join(str(el.value) for g in groupes for el in g)


def test_page_vide_voyants_et_bandeau(installer):
    installer()
    at = page()
    assert at.title[0].value == "Assistant procédures"
    assert "Données fictives — 100 % local" in textes(at)
    assert len([m for m in at.sidebar.markdown if "sf-voyant" in m.value]) == 3
    assert len(at.chat_message) == 0
    assert at.button(key="effacer_assistant").disabled
    assert [at.button(key=f"exemple_{i}").label for i in range(3)] == [
        "Quelle est la porosité maximale du CP-210 ?",
        "Que faut-il vérifier avant de lancer une cuisson autoclave ?",
        "Que faire au changement de lot matière sur la presse-plieuse ?",
    ]


def test_question_reponse_et_sources_puis_effacer(installer):
    llm = FakeLLM(reponse_json())
    installer(llm=llm)
    at = poser(page(), QUESTION)
    tout = textes(at)
    assert len(at.chat_message) == 2
    assert brut(QUESTION) in tout
    assert ":blue-badge[Origine : LLM]" in tout
    assert brut("Fuite de bâche à vide : le test d'étanchéité n'avait pas été enregistré avant cuisson "
                "(NC-2025-014).") in tout
    assert f"- {brut('NC-2025-014')} · {brut('Cause racine')}" in tout
    assert at.expander[0].label == "Passages (1)"
    assert brut(CHUNKS[0].text) in tout
    assert llm.n_calls == 1

    at.button(key="effacer_assistant").click().run()
    assert not at.exception
    assert len(at.chat_message) == 0
    assert at.session_state["assistant_historique"] == []


def test_historique_garde_les_questions(installer):
    installer(llm=FakeLLM(reponse_json(), reponse_json(trouve=False, texte="", sources=[])))
    at = poser(poser(page(), QUESTION), "Horaires de la cantine ?")
    assert len(at.chat_message) == 4
    assert brut(REFUS) in textes(at)


def test_exemple_cliquable_tolerance_sans_llm(installer):
    llm = FakeLLM()
    installer(llm=llm)
    at = page()
    at.button(key="exemple_0").click().run()
    assert not at.exception, at.exception
    tout = textes(at)
    assert ":violet-badge[Origine : Référentiel]" in tout
    assert brut("Porosité de la pièce CP-210 : au plus 2,0 % (bornes incluses).") in tout
    assert f"- {brut('PROC-COMP-01')} · {brut('Tolérances')}" in tout
    assert "Lu dans le référentiel de tolérances, sans LLM." in tout
    assert llm.n_calls == 0


def test_passages_sans_marques_markdown(installer):
    chunk = CHUNKS[2].model_copy(update={"text": "# Mise sous vide\n- **Test d'étanchéité obligatoire** avant cuisson."})
    installer(llm=FakeLLM(reponse_json(sources=[{"doc_id": "PROC-COMP-01", "section": "Mise sous vide"}])),
              retriever=FakeRetriever(chunks=(chunk,)))
    at = poser(page(), QUESTION)
    passage = brut("Mise sous vide\n- Test d'étanchéité obligatoire avant cuisson.")
    assert passage in textes(at)
    assert "**" not in passage and "\\*" not in passage


def test_extraits_si_garde_fou(installer):
    installer(llm=FakeLLM(reponse_json(texte="La pièce est conforme (NC-2025-014).")))
    at = poser(page(), QUESTION)
    tout = textes(at)
    assert ":gray-badge[Origine : Extraits]" in tout
    assert at.warning[0].value == brut(PAS_FIABLE)
    assert at.expander[0].label == "Passages (3)"
    assert "Réponse du LLM écartée" in tout


def test_texte_du_llm_jamais_interprete(installer):
    texte = "Voir [ce lien](http://exemple.invalid) et ![image](x.png) <b>gras</b> (NC-2025-014)."
    installer(llm=FakeLLM(reponse_json(texte=texte)))
    at = poser(page(), QUESTION)
    assert brut(texte) in textes(at)
    assert "[ce lien](http" not in textes(at)


def test_index_absent_message_lisible(installer):
    def en_panne(query, where, k):
        raise RuntimeError("collection absente")

    installer(llm=FakeLLM(), retriever=en_panne)
    at = poser(page(), QUESTION)
    assert at.error[0].value == RAG_INDISPONIBLE
    assert at.session_state["assistant_historique"] == []
