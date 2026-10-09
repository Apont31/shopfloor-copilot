"""Faux déterministes pour les tests de l'agent : aucun appel à Ollama ni à ChromaDB."""

import json

from shopfloor.rag.retriever import RetrievedChunk


class FakeLLM:
    """Renvoie des réponses scriptées dans l'ordre ; une Exception scriptée est levée. Compte ses appels."""

    def __init__(self, *responses: str | Exception):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    @property
    def n_calls(self) -> int:
        return len(self.calls)

    def complete_json(self, system: str, user: str, json_schema: dict) -> str:
        self.calls.append((system, user, json_schema))
        if len(self.calls) > len(self.responses):
            raise AssertionError(f"FakeLLM : appel n°{len(self.calls)} non scripté")
        r = self.responses[len(self.calls) - 1]
        if isinstance(r, Exception):
            raise r
        return r


def proposal_json(**overrides) -> str:
    """Réponse LLM valide pour NC-2026-101 (porosité CP-210), modifiable champ par champ."""
    data = {
        "resume": "Porosité de 2.8 pct relevée au contrôle ultrasons, au-delà du maximum de 2.0 pct.",
        "cause_probable": "Fuite probable de la bâche à vide : le vide a mis longtemps à s'établir, comme sur NC-2025-014.",
        "action_corrective": (
            "Rechercher la fuite de bâche, rendre le test d'étanchéité bloquant avant cuisson "
            "et renforcer le contrôle ultrasons sur les lots suivants."
        ),
        "decision_suggeree": "rebut",
        "sources": ["NC-2025-014", "PROC-COMP-01"],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _chunk(doc_id: str, type_: str, domaine: str, section: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        doc_id=doc_id, type=type_, domaine=domaine, section=section, text=f"[{doc_id}] {text}", score=score
    )


# Deux passages de NC-2025-014 : le nœud doit regrouper par doc_id et garder le meilleur score.
CHUNKS = (
    _chunk("NC-2025-014", "nc_historique", "composite", "Cause racine",
           "Fuite de bâche à vide, test d'étanchéité non enregistré avant cuisson.", 0.82),
    _chunk("NC-2025-014", "nc_historique", "composite", "Action corrective",
           "Test d'étanchéité rendu point d'arrêt, contrôle ultrasons renforcé.", 0.74),
    _chunk("PROC-COMP-01", "procedure", "composite", "Mise sous vide",
           "Test d'étanchéité obligatoire avant cuisson.", 0.69),
    _chunk("PROC-QUA-01", "transverse", "qualite", "Décisions possibles",
           "Retouche, rebut ou dérogation, avec validation humaine.", 0.51),
)


def fake_retriever(query: str, where: dict | None) -> list[RetrievedChunk]:
    return list(CHUNKS)
