from app.tools.sandbox import failure_nudge


def test_code_bug_gets_blame_clarification():
    stderr = "Traceback (most recent call last):\n  ...\nNameError: name 'requests' is not defined"
    nudge = failure_nudge(stderr)
    assert "[Код упал" in nudge
    assert "баг в ТВОЁМ коде" in nudge


def test_network_error_no_false_blame():
    stderr = "Traceback ...\nurllib.error.HTTPError: HTTP Error 503: Service Unavailable"
    nudge = failure_nudge(stderr)
    assert "[Код упал" in nudge
    assert "баг в ТВОЁМ коде" not in nudge  # тут внешний сервис и правда мог глючить


def test_type_and_key_errors_are_code_bugs():
    for exc in ("TypeError: string indices", "KeyError: slice(None, 2, None)"):
        assert "баг в ТВОЁМ коде" in failure_nudge(exc)
