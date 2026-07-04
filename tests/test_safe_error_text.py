import html

from app.services.alerts import safe_error_text


def test_redacts_openrouter_key():
    exc = ValueError("bad key sk-or-v1-abcdef1234567890 rejected")
    text = safe_error_text(exc)
    assert "sk-or-" not in text
    assert "[redacted]" in text


def test_redacts_tavily_key():
    exc = RuntimeError("Tavily auth failed: tvly-XyZ123abc")
    text = safe_error_text(exc)
    assert "tvly-" not in text


def test_redacts_telegram_bot_token():
    exc = RuntimeError("call failed: 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1")
    text = safe_error_text(exc)
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1" not in text


def test_redacts_url_credentials():
    exc = ConnectionError("postgresql://gennady:s3cretpass@postgres:5432/db down")
    text = safe_error_text(exc)
    assert "s3cretpass" not in text
    assert "postgres:5432" in text  # хост остаётся — полезен для диагностики


def test_redacts_key_value_secrets():
    exc = ValueError("config error: password=hunter2 api_key: abc123")
    text = safe_error_text(exc)
    assert "hunter2" not in text
    assert "abc123" not in text


def test_truncates_to_limit():
    exc = ValueError("x" * 500)
    assert len(safe_error_text(exc, 100)) == 100


def test_includes_type_name_and_survives_html_escape():
    exc = ValueError("tag <b> & ampersand")
    text = safe_error_text(exc)
    assert text.startswith("ValueError:")
    escaped = html.escape(text)
    assert "<b>" not in escaped
    assert "&lt;b&gt;" in escaped
