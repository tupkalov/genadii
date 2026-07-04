import json
import uuid

import pytest

from app.llm import embeddings

VECTOR = [0.1, 0.2, 0.3]


class _FakeResponse:
    def json(self):
        return {"data": [{"embedding": VECTOR}]}


class _FakeRedisDown:
    async def get(self, key):
        raise ConnectionError("redis down")

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")


@pytest.fixture
def api_counter(monkeypatch):
    calls = {"n": 0}

    async def fake_request(request_fn):
        calls["n"] += 1
        return _FakeResponse()

    monkeypatch.setattr(embeddings, "request_with_retry", fake_request)
    return calls


async def test_second_call_hits_cache(api_counter):
    text = f"кэш-тест {uuid.uuid4()}"  # уникальный текст — чистый ключ в Redis
    first = await embeddings.embed(text)
    second = await embeddings.embed(text)
    assert first == second == VECTOR
    assert api_counter["n"] == 1


async def test_different_texts_do_not_share_cache(api_counter):
    await embeddings.embed(f"один {uuid.uuid4()}")
    await embeddings.embed(f"другой {uuid.uuid4()}")
    assert api_counter["n"] == 2


async def test_redis_down_degrades_to_direct_call(api_counter, monkeypatch):
    monkeypatch.setattr(embeddings, "_redis", _FakeRedisDown())
    text = f"без редиса {uuid.uuid4()}"
    assert await embeddings.embed(text) == VECTOR
    assert await embeddings.embed(text) == VECTOR
    assert api_counter["n"] == 2  # кэша нет — оба раза напрямую


async def test_cached_value_is_json_roundtrip(api_counter):
    text = f"json {uuid.uuid4()}"
    vector = await embeddings.embed(text)
    assert json.loads(json.dumps(vector)) == vector
