import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from app.core.search import embeddings
from app.core.search.embeddings import EmbeddingsUnavailableError


@pytest.fixture(autouse=True)
def reset_embedding_guardrails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_circuit_open_until", 0.0)
    monkeypatch.setattr(embeddings, "_circuit_reason", None)
    monkeypatch.setattr(embeddings, "_embedding_slots", asyncio.Semaphore(2))


def test_client_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(embeddings.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(embeddings.settings, "SEARCH_EMBEDDING_TIMEOUT_SECONDS", 7.5)
    monkeypatch.setattr("openai.AsyncOpenAI", fake_client)

    embeddings._client()

    assert captured["api_key"] == "test-key"
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 7.5


def test_provider_failure_opens_circuit_and_skips_followup_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FailingEmbeddings:
        async def create(self, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            raise APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com/v1/embeddings")
            )

    async def close() -> None:
        return None

    client = SimpleNamespace(embeddings=FailingEmbeddings(), close=close)
    monkeypatch.setattr(embeddings, "_client", lambda: client)
    monkeypatch.setattr(
        embeddings.settings, "SEARCH_EMBEDDING_CIRCUIT_BREAKER_SECONDS", 60.0
    )

    async def run() -> None:
        with pytest.raises(EmbeddingsUnavailableError):
            await embeddings.embed_batch(["first"])
        with pytest.raises(EmbeddingsUnavailableError, match="retry in"):
            await embeddings.embed_batch(["second"])

    asyncio.run(run())
    assert calls == 1


def test_embedding_requests_respect_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    max_active = 0

    class SlowEmbeddings:
        async def create(self, **kwargs: object) -> object:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[float(kwargs["input"][0])])]
            )

    async def close() -> None:
        return None

    client = SimpleNamespace(embeddings=SlowEmbeddings(), close=close)
    monkeypatch.setattr(embeddings, "_client", lambda: client)

    async def run() -> list[list[list[float]]]:
        return list(
            await asyncio.gather(*(embeddings.embed_batch([str(i)]) for i in range(6)))
        )

    results = asyncio.run(run())
    assert max_active == 2
    assert results == [[[float(i)]] for i in range(6)]
