"""Lecture des documents Markdown à front-matter YAML (corpus et fiches NC)."""

from pathlib import Path

import yaml


def split_front_matter(text: str) -> tuple[dict, str]:
    """Sépare le front-matter YAML (entre deux lignes ---) du corps Markdown."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("front-matter absent : le fichier doit commencer par ---")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("front-matter non fermé")
    meta = yaml.safe_load(text[4:end])
    if not isinstance(meta, dict):
        raise ValueError("front-matter invalide : un dictionnaire YAML est attendu")
    return meta, text[end + 5 :]


def read_document(path: str | Path) -> tuple[dict, str]:
    return split_front_matter(Path(path).read_text(encoding="utf-8"))
