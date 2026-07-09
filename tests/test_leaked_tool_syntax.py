from app.services.llm_chat import _has_leaked_tool_syntax


def test_detects_real_deepseek_leak():
    # Реальный паттерн из бага (message id=209, deepseek/deepseek-v4-flash-20260423):
    # модель написала псевдо-вызов инструмента текстом вместо structured tool_calls.
    leaked = (
        '<｜｜DSML｜｜tool_calls>\n'
        '<｜｜DSML｜｜invoke name="run_saved_script">'
        '{"name": "todoist_digest"}</invoke>'
    )
    assert _has_leaked_tool_syntax(leaked) is True


def test_detects_tool_calls_bracket_marker():
    assert _has_leaked_tool_syntax("[TOOL_CALLS] run_python({...})") is True


def test_detects_invoke_name_marker():
    assert _has_leaked_tool_syntax('<invoke name="web_search">') is True


def test_detects_function_dot_name_line():
    # Живой кейс 09.07: «function.RunPython» отдельной строкой + json-аргументы
    # текстом — инструмент реально не вызван, а код утёк пользователю в чат
    leaked = (
        "Ошибка: в API что-то поменяли, но сейчас срочно починю код 🛠️\n\n"
        "function.RunPython\n"
        "json\n"
        '{"code": "import requests\\n..."}'
    )
    assert _has_leaked_tool_syntax(leaked) is True


def test_detects_functions_plural_and_snake_case():
    assert _has_leaked_tool_syntax('functions.run_python\n{"code": "1"}') is True


def test_normal_text_is_clean():
    assert _has_leaked_tool_syntax("Вот твой дайджест на сегодня: 3 задачи.") is False
    # «function.» в середине предложения — не утечка
    assert (
        _has_leaked_tool_syntax("В JS метод function.call() зовёт функцию.") is False
    )


def test_empty_and_none_are_clean():
    assert _has_leaked_tool_syntax("") is False
    assert _has_leaked_tool_syntax(None) is False
