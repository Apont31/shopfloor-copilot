"""Chronométrage des appels au LLM (affichage et journal uniquement, aucune influence sur la décision)."""

import time


class ChronoLLM:
    """Enveloppe un LLMClient pour mesurer la durée de chaque appel (affichage uniquement)."""

    def __init__(self, llm):
        self.llm = llm
        self.durations: list[float] = []

    def complete_json(self, system: str, user: str, json_schema: dict) -> str:
        t0 = time.perf_counter()
        try:
            return self.llm.complete_json(system, user, json_schema)
        finally:
            self.durations.append(time.perf_counter() - t0)
