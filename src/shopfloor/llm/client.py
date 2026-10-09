"""Interface du client LLM. Aucune implémentation réelle ici : le faux LLM des tests suffit à l'étape 6."""

from typing import Protocol


class LLMError(Exception):
    """Échec d'appel au LLM (serveur injoignable, timeout…). Le nœud bascule alors sur le repli."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, json_schema: dict) -> str:
        """Renvoie le texte brut produit par le modèle. Le parsing et la validation se font dans le nœud."""
        ...
