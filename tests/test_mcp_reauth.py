"""Auth-ошибка MCP → точная команда реавторизации, без выдуманного «reauth»."""
from app.services import mcp
from app.services.mcp_auth import ReauthRequired


def test_looks_like_auth_required_typed():
    assert mcp.looks_like_auth_required(ReauthRequired("нужна авторизация")) is True


def test_looks_like_auth_required_in_taskgroup():
    # SDK заворачивает исключение в anyio TaskGroup — распаковка обязана достать
    grouped = BaseExceptionGroup("unhandled errors in a TaskGroup", [ReauthRequired("x")])
    assert mcp.looks_like_auth_required(grouped) is True


def test_looks_like_auth_required_401_text():
    assert mcp.looks_like_auth_required(RuntimeError("HTTP 401 Unauthorized")) is True


def test_looks_like_auth_required_negative():
    assert mcp.looks_like_auth_required(RuntimeError("connection refused")) is False


def test_reauth_instruction_oauth_gives_real_command():
    text = mcp.reauth_instruction("todoist", oauth=True)
    assert "/mcp auth todoist" in text
    # Явный запрет выдуманных команд вроде /mcp reauth и фейкового «сохранил локально»
    assert "reauth" in text.lower()  # упомянуто как то, чего делать нельзя
    assert "локально" in text
    assert "притвор" in text.lower()


def test_reauth_instruction_static_token_suggests_readd():
    text = mcp.reauth_instruction("myserver", oauth=False)
    assert "/mcp add myserver" in text
    assert "/mcp auth" not in text  # у статического токена другой путь
