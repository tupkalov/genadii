from app.tools.registry import ToolContext
from app.tools.scripts import _get_script, _list_scripts, _save_script


async def test_saved_script_is_isolated_per_workspace(
    session, workspace, other_workspace, user
):
    ctx_a = ToolContext(session=session, workspace=workspace, user=user)
    ctx_b = ToolContext(session=session, workspace=other_workspace, user=user)

    await _save_script(ctx_a, "digest", "print('digest for a')", "test script")
    await session.commit()

    # Другой workspace не видит скрипт первого ни по имени, ни в списке
    assert await _get_script(ctx_b, "digest") is None
    listing = await _list_scripts(ctx_b)
    assert "digest" not in listing

    listing_a = await _list_scripts(ctx_a)
    assert "digest" in listing_a


async def test_same_name_in_two_workspaces_does_not_collide(
    session, workspace, other_workspace, user
):
    ctx_a = ToolContext(session=session, workspace=workspace, user=user)
    ctx_b = ToolContext(session=session, workspace=other_workspace, user=user)

    await _save_script(ctx_a, "digest", "print('a')")
    await _save_script(ctx_b, "digest", "print('b')")
    await session.commit()

    script_a = await _get_script(ctx_a, "digest")
    script_b = await _get_script(ctx_b, "digest")
    assert script_a.code == "print('a')"
    assert script_b.code == "print('b')"
