import shopfloor
from shopfloor.config import Settings

ENV_DEFAULTS = {
    "OLLAMA_HOST": "http://localhost:11434",
    "LLM_MODEL": "qwen2.5:7b-instruct",
    "EMBED_MODEL": "nomic-embed-text",
    "CHROMA_DIR": ".chroma",
    "ERP_DB": "erp.db",
    "ERP_URL": "http://127.0.0.1:8000",
}


def test_import_shopfloor():
    assert shopfloor.__name__ == "shopfloor"


def test_settings_defaults(monkeypatch):
    for name in ENV_DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.ollama_host == ENV_DEFAULTS["OLLAMA_HOST"]
    assert s.llm_model == ENV_DEFAULTS["LLM_MODEL"]
    assert s.embed_model == ENV_DEFAULTS["EMBED_MODEL"]
    assert s.chroma_dir == ENV_DEFAULTS["CHROMA_DIR"]
    assert s.erp_db == ENV_DEFAULTS["ERP_DB"]
    assert s.erp_url == ENV_DEFAULTS["ERP_URL"]


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "autre-modele")
    assert Settings().llm_model == "autre-modele"
