import os

from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

from uniclaw.console import run
from uniclaw.console import output_renderer
from uniclaw.console import session_panel
from uniclaw.console.run import MouseScrollableFormattedTextControl, TUIApp


def _new_tui() -> TUIApp:
    TUIApp._instance = None
    tui = TUIApp({"verbose": False})
    tui.session_panel_visible = False
    tui._chrome_height = 5
    return tui


def _text(fragments: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in fragments)


def test_output_tail_accounts_for_soft_wrapped_rows(monkeypatch):
    monkeypatch.setattr(
        output_renderer.shutil,
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
        output_renderer.shutil,
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
        output_renderer.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((20, 7)),
    )
    tui = _new_tui()
    tui.output_lines = [[("", "A" * 80)], [("", "LAST")]]

    rendered = _text(tui._get_output_text())

    assert rendered.split("\n") == ["A" * 20, "LAST"]


def test_session_list_scrolls_independently(monkeypatch):
    monkeypatch.setattr(
        session_panel.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((80, 8)),
    )
    tui = _new_tui()
    tui.session_panel_visible = True
    tui.session_panel_focused = True
    tui.session_items = [
        {
            "session_id": f"s-{idx}",
            "title": f"Session {idx}",
            "end_time": "2026-05-23T12:00:00",
            "message_count": idx,
        }
        for idx in range(6)
    ]

    tui._scroll_sessions(2)
    rendered = _text(tui._get_session_text())

    assert "Session 0" not in rendered
    assert "Session 2" in rendered
    assert tui.scroll_offset == 0


def test_mouse_scroll_control_handles_wheel_events():
    calls = []
    control = MouseScrollableFormattedTextControl(
        text=[("", "content")],
        on_scroll_up=lambda: calls.append("up"),
        on_scroll_down=lambda: calls.append("down"),
    )

    control.mouse_handler(
        MouseEvent(
            position=Point(x=0, y=0),
            event_type=MouseEventType.SCROLL_UP,
            button=MouseButton.NONE,
            modifiers=frozenset(),
        )
    )
    control.mouse_handler(
        MouseEvent(
            position=Point(x=0, y=0),
            event_type=MouseEventType.SCROLL_DOWN,
            button=MouseButton.NONE,
            modifiers=frozenset(),
        )
    )

    assert calls == ["up", "down"]
