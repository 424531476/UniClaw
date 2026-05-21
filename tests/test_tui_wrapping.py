import os

from console import run
from console.run import TUIApp


def _new_tui() -> TUIApp:
    TUIApp._instance = None
    tui = TUIApp({"verbose": False})
    tui.conversation_panel_visible = False
    tui._chrome_height = 5
    return tui


def _text(fragments: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in fragments)


def test_output_tail_accounts_for_soft_wrapped_rows(monkeypatch):
    monkeypatch.setattr(
        run.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((20, 8)),
    )
    tui = _new_tui()
    tui.output_lines = [[("", "A" * 120)], [("", "LAST")]]

    rendered = _text(tui._get_output_text())

    assert rendered.split("\n") == ["A" * 20, "A" * 20, "LAST"]
    assert tui._count_visible_lines() == 7


def test_soft_wrap_preserves_fragment_styles():
    wrapped = TUIApp._wrap_fragment_lines(
        [[("fg:red", "abcd"), ("fg:green", "efgh")]],
        5,
    )

    assert wrapped == [
        [("fg:red", "abcd"), ("fg:green", "e")],
        [("fg:green", "fgh")],
    ]


def test_soft_wrap_handles_wide_cjk_characters():
    wrapped = TUIApp._wrap_fragment_lines([[("", "abc工具已禁用")]], 8)

    assert wrapped == [[("", "abc工具")], [("", "已禁用")]]


def test_active_spinner_stays_visible_when_output_is_scrolled(monkeypatch):
    monkeypatch.setattr(
        run.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((20, 8)),
    )
    monkeypatch.setattr(run.TUISpinner, "get_display", lambda: "SPINNER")
    tui = _new_tui()
    tui.output_lines = [[("", "A" * 120)]]
    tui.scroll_offset = 1

    rendered = _text(tui._get_output_text())

    assert rendered.split("\n")[-1] == "SPINNER"


def test_output_tail_uses_actual_short_viewport_height(monkeypatch):
    monkeypatch.setattr(
        run.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((20, 7)),
    )
    tui = _new_tui()
    tui.output_lines = [[("", "A" * 80)], [("", "LAST")]]

    rendered = _text(tui._get_output_text())

    assert rendered.split("\n") == ["A" * 20, "LAST"]
