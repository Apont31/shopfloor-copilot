"""OllamaLLM sans Ollama : faux client injecté, ou hôte injoignable."""

import httpx
import ollama
import pytest

from shopfloor.config import Settings
from shopfloor.errors import OLLAMA_INDISPONIBLE, OllamaUnavailableError
from shopfloor.llm.client import LLMError, LLMUnavailableError
from shopfloor.llm.ollama_client import OllamaLLM
from shopfloor.rag.embeddings import OllamaEmbedder

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


class FakeOllamaClient:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def llm(result, **settings) -> tuple[OllamaLLM, FakeOllamaClient]:
    fake = FakeOllamaClient(result)
    return OllamaLLM(Settings(**settings), client=fake), fake


def test_appel_structure_et_options_deterministes():
    client, fake = llm({"message": {"content": '{"a": "x"}'}}, llm_model="modele-test")
    assert client.complete_json("système", "utilisateur", SCHEMA) == '{"a": "x"}'
    assert fake.kwargs["model"] == "modele-test"
    assert fake.kwargs["format"] == SCHEMA
    assert fake.kwargs["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096}
    assert fake.kwargs["messages"] == [
        {"role": "system", "content": "système"},
        {"role": "user", "content": "utilisateur"},
    ]


def test_modele_et_hote_lus_dans_settings():
    client = OllamaLLM(Settings(ollama_host="http://127.0.0.1:9", llm_model="m"), timeout=7)
    assert client.model == "m"
    assert str(client.client._client.base_url).startswith("http://127.0.0.1:9")
    assert client.client._client.timeout.read == 7


def test_timeout_par_defaut_120_s():
    assert OllamaLLM(Settings()).client._client.timeout.read == 120


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("timed out"),
    ollama.ResponseError("model not found", 404),
])
def test_erreurs_traduites_en_llm_error(error):
    client, _ = llm(error)
    with pytest.raises(LLMError, match=type(error).__name__):
        client.complete_json("s", "u", SCHEMA)


@pytest.mark.parametrize("response", [
    {"message": {"content": ""}},
    {"message": {"content": "   \n"}},
    {"message": {"content": None}},
])
def test_reponse_vide_llm_error(response):
    client, _ = llm(response)
    with pytest.raises(LLMError, match="réponse vide"):
        client.complete_json("s", "u", SCHEMA)


def test_reponse_malformee_llm_error():
    client, _ = llm({"inattendu": True})
    with pytest.raises(LLMError):
        client.complete_json("s", "u", SCHEMA)


def test_hote_injoignable_llm_error():
    client = OllamaLLM(Settings(ollama_host="http://127.0.0.1:9"), timeout=2)
    with pytest.raises(LLMError):
        client.complete_json("s", "u", SCHEMA)


# --- Étape 7b : Ollama injoignable -> message d'action unique ---------------------------------------

@pytest.mark.parametrize("error", [
    ConnectionError("Failed to connect to Ollama"),
    httpx.ConnectError("connexion refusée"),
    httpx.ConnectTimeout("délai de connexion"),
])
def test_llm_injoignable_message_ollama_indisponible(error):
    client, _ = llm(error)
    with pytest.raises(LLMUnavailableError, match="^Ollama indisponible : lancez l'application Ollama$"):
        client.complete_json("s", "u", SCHEMA)


def test_llm_injoignable_reste_une_llm_error():
    """Le nœud propose_action continue de basculer sur le repli (LLMError)."""
    assert issubclass(LLMUnavailableError, LLMError)
    assert issubclass(LLMUnavailableError, OllamaUnavailableError)


def test_hote_injoignable_message_ollama_indisponible():
    client = OllamaLLM(Settings(ollama_host="http://127.0.0.1:9"), timeout=2)
    with pytest.raises(LLMUnavailableError) as exc:
        client.complete_json("s", "u", SCHEMA)
    assert str(exc.value) == OLLAMA_INDISPONIBLE


def test_embedder_hote_injoignable_message_ollama_indisponible():
    embedder = OllamaEmbedder(Settings(ollama_host="http://127.0.0.1:9"))
    with pytest.raises(OllamaUnavailableError) as exc:
        embedder.embed_query("porosité")
    assert str(exc.value) == OLLAMA_INDISPONIBLE == "Ollama indisponible : lancez l'application Ollama"
