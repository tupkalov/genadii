import asyncio

from app.bot.handlers.chat import _StreamEditor


class _FakePlaceholder:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, parse_mode=None):
        self.edits.append(text)


async def test_two_fast_feeds_schedule_single_flush():
    placeholder = _FakePlaceholder()
    editor = _StreamEditor(placeholder, interval=0.0)  # каждый feed «созрел» для правки

    editor.feed("раз")
    assert editor._flush_scheduled is True
    editor.feed("раз два")  # до запуска первого _flush — дубль не создаётся

    await asyncio.sleep(0.05)  # даём созданной задаче отработать
    assert placeholder.edits == ["раз два ▍"]  # одна правка, с последним текстом
    assert editor._flush_scheduled is False


async def test_flush_failure_is_suppressed():
    class _Broken:
        async def edit_text(self, text, parse_mode=None):
            raise RuntimeError("429 too many requests")

    editor = _StreamEditor(_Broken(), interval=0.0)
    editor.feed("текст")
    await asyncio.sleep(0.05)  # не должно уронить event loop
    assert editor._flush_scheduled is False
