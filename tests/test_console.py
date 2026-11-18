"""The setup spinner: drawn only on a terminal, and always cleared before other output."""

from __future__ import annotations

import io
import time

from kit import console


class FakeTerminal(io.StringIO):
    def isatty(self):
        return True


def screen(text: str) -> list[str]:
    """What a terminal shows for `text`: `\\r` returns to the start of the line and later characters overwrite."""
    lines, line, col = [], [], 0
    for ch in text:
        if ch == "\n":
            lines.append("".join(line).rstrip())
            line, col = [], 0
        elif ch == "\r":
            col = 0
        else:
            if col < len(line):
                line[col] = ch
            else:
                line.append(ch)
            col += 1
    lines.append("".join(line).rstrip())
    return lines


def wait_for_a_frame(stream, after="\n"):
    """Wait until the spinner has drawn after the last `after` in the output."""
    deadline = time.monotonic() + 5
    while not any(frame in stream.getvalue().split(after)[-1] for frame in console.SPINNER_FRAMES):
        assert time.monotonic() < deadline, "the spinner never drew"
        time.sleep(0.005)


def test_spinner_draws_nothing_when_output_is_not_a_terminal():
    stream = io.StringIO()
    with console.spinner(stream=stream, interval=0.001):
        time.sleep(0.05)
    assert stream.getvalue() == ""


def test_spinner_on_a_terminal_draws_ascii_frames_and_leaves_a_clean_line():
    stream = FakeTerminal()
    with console.spinner(stream=stream, interval=0.001):
        wait_for_a_frame(stream)
    assert stream.getvalue().isascii()
    assert screen(stream.getvalue()) == [""]


def test_messages_printed_while_spinning_are_not_garbled(monkeypatch):
    stream = FakeTerminal()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)
    with console.spinner(interval=0.001):
        wait_for_a_frame(stream)
        console.say("  history traces: batch 1 of 3")
        wait_for_a_frame(stream, after="batch 1 of 3")
        console.warn("trace not confirmed yet")
    console.say("done")
    assert screen(stream.getvalue()) == [
        "  history traces: batch 1 of 3",
        "Warning: trace not confirmed yet",
        "done",
        "",
    ]


def test_spinner_line_is_cleared_when_the_step_raises(monkeypatch):
    stream = FakeTerminal()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)
    try:
        with console.spinner(interval=0.001):
            wait_for_a_frame(stream)
            raise RuntimeError("boom")
    except RuntimeError:
        console.error("LF-KEYPAIR", "The tracing keys were rejected.", "Paste them again.")
    assert screen(stream.getvalue()) == [
        "",
        "[LF-KEYPAIR] The tracing keys were rejected.",
        "Fix: Paste them again.",
        "",
    ]
