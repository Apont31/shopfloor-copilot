"""Assistant procédures avec le vrai Ollama (LLM + embeddings) sur data/eval/assistant_cases.yaml.

Lancé à la main : pytest -m llm tests/test_assistant_llm.py -v -s (le détail et le taux sont affichés par print).
Aucune assertion sur la formulation : seuls l'origine, les sources et le refus sont vérifiés.
"""

import time
from pathlib import Path

import pytest
import yaml

from shopfloor.assistant import Answer, AssistantDeps, answer
from shopfloor.llm.chrono import ChronoLLM
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.oracle.loader import load_tolerances
from shopfloor.rag.embeddings import OllamaEmbedder
from shopfloor.rag.ingest import ingest
from shopfloor.rag.retriever import make_retriever

pytestmark = pytest.mark.llm

ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((ROOT / "data" / "eval" / "assistant_cases.yaml").read_text(encoding="utf-8"))["cases"]
TAUX_MIN = 6 / 8


def reussi(case: dict, rep: Answer) -> bool:
    if case.get("expected_refus"):
        return rep.refus
    return not rep.refus and case["expected_doc_id"] in {s.doc_id for s in rep.sources}


@pytest.fixture(scope="module")
def deps(tmp_path_factory) -> AssistantDeps:
    chroma_dir = tmp_path_factory.mktemp("chroma")
    embedder = OllamaEmbedder()
    ingest(embedder, ROOT / "data" / "docs", chroma_dir)
    return AssistantDeps(
        tolerances=load_tolerances(ROOT / "config" / "tolerances.yaml"),
        retriever=make_retriever(chroma_dir, embedder),
        llm=OllamaLLM(),
    )


def test_evaluation_assistant(deps):
    resultats = []
    for case in CASES:
        chrono = ChronoLLM(deps.llm)
        t0 = time.perf_counter()
        rep = answer(case["question"], AssistantDeps(tolerances=deps.tolerances, retriever=deps.retriever, llm=chrono))
        duree = time.perf_counter() - t0
        ok = reussi(case, rep)
        resultats.append((case, rep, ok, duree))
        sources = ", ".join(f"{s.doc_id} ({s.section})" for s in rep.sources) or "aucune"
        print(f"\n[{'OK' if ok else 'ÉCHEC'}] {case['kind']:<11} {duree:5.1f} s  LLM {len(chrono.durations)} appel(s)"
              f"  origine={rep.origine}{' refus' if rep.refus else ''}\n  Q : {case['question']}\n  R : {rep.texte}"
              f"\n  Sources : {sources}" + (f"\n  Motifs : {' ; '.join(rep.motifs)}" if rep.motifs else ""))

        if case["kind"] == "tolerance":  # chemin déterministe : jamais de LLM
            assert rep.origine == "referentiel" and rep.llm_calls == 0, case["question"]
        if case.get("expected_refus"):  # hors corpus : jamais une réponse du LLM présentée comme fiable
            assert not (rep.origine == "llm" and not rep.refus), case["question"]

    n_ok = sum(ok for _, _, ok, _ in resultats)
    durees = [d for _, rep, _, d in resultats if rep.origine != "referentiel"]
    print(f"\nTaux de réussite : {n_ok}/{len(resultats)}"
          f" ; durée moyenne hors référentiel : {sum(durees) / max(len(durees), 1):.1f} s")
    assert n_ok / len(resultats) >= TAUX_MIN
