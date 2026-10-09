"""Configuration lue depuis les variables d'environnement."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str):
    return field(default_factory=lambda: os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    ollama_host: str = _env("OLLAMA_HOST", "http://localhost:11434")
    llm_model: str = _env("LLM_MODEL", "qwen2.5:7b-instruct")
    embed_model: str = _env("EMBED_MODEL", "nomic-embed-text")
    chroma_dir: str = _env("CHROMA_DIR", ".chroma")
    erp_db: str = _env("ERP_DB", "erp.db")
    erp_url: str = _env("ERP_URL", "http://127.0.0.1:8000")
