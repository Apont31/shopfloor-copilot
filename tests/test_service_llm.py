"""run-inbox avec le vrai Ollama (LLM + embeddings) sur les 3 fiches d'origine (étape 9).

Lancé à la main : pytest -m llm -v -rA (le récapitulatif et la durée totale sont affichés par print).
Aucune assertion sur la formulation du LLM : seuls les verdicts, statuts et origines sont vérifiés.
"""

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shopfloor import cli
from shopfloor.agent.graph import Deps
from shopfloor.erp.api import create_app
from shopfloor.erp.client import ErpClient
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import make_retriever
from shopfloor.service import Service

pytestmark = pytest.mark.llm

ROOT = Path(__file__).resolve().parents[1]
TOLERANCES = load_tolerances(ROOT / "config" / "tolerances.yaml")
ORIGINE = {"NC-2026-101": "NON_CONFORME", "NC-2026-102": "CONFORME", "NC-2026-103": "INDETERMINE"}


def test_run_inbox_ollama_trois_fiches_d_origine(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for nc_id in ORIGINE:
        shutil.copy(ROOT / "data" / "nc_inbox" / f"{nc_id}.md", inbox / f"{nc_id}.md")
    embedder = OllamaEmbedder()
    ingest(embedder, ROOT / "data" / "docs", tmp_path / "chroma")
    erp = ErpClient("http://testserver", http_client=TestClient(create_app(tmp_path / "erp.db")))
    deps = Deps(
        tolerances=TOLERANCES,
        retriever=make_retriever(tmp_path / "chroma", embedder),
        llm=OllamaLLM(),
        erp=erp,
    )

    with Service(deps, state_db=tmp_path / "state.db", journal_db=tmp_path / "journal.db") as service:
        t0 = time.perf_counter()
        code = cli.run_inbox(service, inbox)
        duree = time.perf_counter() - t0
        runs = {r.nc_id: r for r in service.journal.list_runs()}
        pending = service.list_pending()

    out = capsys.readouterr().out
    with capsys.disabled():
        print(f"\n{out}Durée totale de run-inbox : {duree:.1f} s")

    assert code == 0
    assert {k: r.verdict for k, r in runs.items()} == ORIGINE
    assert {r.statut for r in runs.values()} == {"en_attente"}
    assert len(pending) == 3
    assert runs["NC-2026-101"].llm_ms is not None  # le LLM a été appelé (origine llm, ou repli)
    for nc_id in ("NC-2026-102", "NC-2026-103"):
        assert (runs[nc_id].origine, runs[nc_id].llm_ms) == ("deterministe", None)
