from app.bot.formatting import _demote_html, md_to_html


def test_bold_and_italic():
    assert md_to_html("**жирный** и *курсив*") == "<b>жирный</b> и <i>курсив</i>"


def test_inline_code_not_formatted_inside():
    assert md_to_html("`**not bold**`") == "<code>**not bold**</code>"


def test_code_block():
    assert md_to_html("```\nprint(1)\n```") == "<pre>print(1)</pre>"


def test_link():
    assert (
        md_to_html("[текст](https://example.com)")
        == '<a href="https://example.com">текст</a>'
    )


def test_html_escaping():
    assert md_to_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_list_bullet():
    assert md_to_html("- пункт") == "• пункт"


def test_demote_html_bold():
    assert _demote_html("<b>жирный</b>") == "**жирный**"


def test_demote_html_code():
    assert _demote_html("<code>x = 1</code>") == "`x = 1`"
