"""client.chat: не-JSON от OpenRouter → чистый LlmError, а не голый JSONDecodeError.

Реальный сбой: шлюз вернул HTML-страницу ошибки, response.json() падал
JSONDecodeError, ломая крон сжатия истории каскадом."""
import pytest

from app.config import get_settings
from app.llm import client


class _FakeResp:
    status_code = 502
    text = "<html>502 Bad Gateway</html>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


async def test_chat_wraps_non_json_in_llmerror(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "test-key")

    async def _fake_request(_do):
        return _FakeResp()

    monkeypatch.setattr(client, "request_with_retry", _fake_request)

    with pytest.raises(client.LlmError) as exc:
        await client.chat([{"role": "user", "content": "hi"}], "some/model")
    assert "не-JSON" in str(exc.value)
    assert "502" in str(exc.value)
