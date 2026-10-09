import ollama
import pytest

from shopfloor.config import Settings

pytestmark = pytest.mark.llm


@pytest.fixture(scope="module")
def settings():
    return Settings()


@pytest.fixture(scope="module")
def client(settings):
    return ollama.Client(host=settings.ollama_host)


def test_llm_repond(client, settings):
    resp = client.generate(
        model=settings.llm_model,
        prompt="Réponds uniquement par le mot OK.",
        options={"temperature": 0, "num_predict": 10},
    )
    assert resp["response"].strip()


def test_embedding_dimension_768(client, settings):
    resp = client.embed(model=settings.embed_model, input="Épaisseur de peinture hors tolérance.")
    assert len(resp["embeddings"][0]) == 768
