"""Dismiss one known informational dialog while a COM call runs.

Solid Edge has a single UI thread. A modal it raises during a COM call blocks
that call until somebody clicks, and ``DisplayAlerts`` does not suppress every
one: ``StructuralFrames.Add`` raises an informational "The Segments group of
commands are replaced with the 3D Draw group ..." box (OK, plus "Do not show
this message again") the first time in a session, and the call sat on it for
as long as it took to click OK (Solid Edge 2026). The second frame in the
session raised nothing.

This is deliberately narrow: it watches, for the duration of one call, for a
``#32770`` dialog whose text starts with a given prefix, and clicks its OK.
Anything else is left alone -- an unexpected dialog is information, not
something to click through blindly.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any

from .logging import get_logger

_logger = get_logger(__name__)

_DIALOG_CLASS = "#32770"
_BM_CLICK = 0x00F5
_IDOK = 1


def _user32() -> Any | None:
    if sys.platform != "win32":
        return None
    return getattr(ctypes, "windll", None) and ctypes.windll.user32


def _visible_dialogs() -> list[tuple[int, str, list[str]]]:
    """Every visible ``#32770`` window: (hwnd, title, child texts)."""
    user32 = _user32()
    if user32 is None:
        return []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found: list[tuple[int, str, list[str]]] = []

    def on_window(hwnd: Any, _: Any) -> bool:
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value == _DIALOG_CLASS and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            texts: list[str] = []

            def on_child(child: Any, _: Any) -> bool:
                text = ctypes.create_unicode_buffer(1024)
                user32.GetWindowTextW(child, text, 1024)
                if text.value:
                    texts.append(text.value)
                return True

            user32.EnumChildWindows(hwnd, proto(on_child), 0)
            found.append((int(hwnd), title.value, texts))
        return True

    user32.EnumWindows(proto(on_window), 0)
    return found


def _click_ok(hwnd: int) -> bool:
    user32 = _user32()
    if user32 is None:
        return False
    button = user32.GetDlgItem(hwnd, _IDOK)
    if not button:
        return False
    user32.SendMessageW(button, _BM_CLICK, 0, 0)
    return True


# The dialog's text follows the UI language, so a prefix has to be listed per
# language. The Japanese one was read off Solid Edge 2026 Community Edition
# with a Japanese UI: "今後セグメントコマンドは機能強化されないので、..." -- the
# English prefix never matched it, and StructuralFrames.Add sat on the modal
# until someone clicked OK.
SEGMENTS_DIALOG_PREFIXES: tuple[str, ...] = (
    "The Segments group of commands",
    "今後セグメントコマンドは",
)


class dismiss_informational_dialog:
    """While active, click OK on the dialog whose text starts with ``text_prefix``.

    ``text_prefix`` may be one prefix or a tuple of them (one per UI language).
    """

    def __init__(self, text_prefix: str | tuple[str, ...], poll_seconds: float = 0.2) -> None:
        self.text_prefix = text_prefix
        self.poll_seconds = poll_seconds
        self.dismissed = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _watch(self) -> None:
        while not self._stop.is_set():
            for hwnd, title, texts in _visible_dialogs():
                if any(t.startswith(self.text_prefix) for t in texts) and _click_ok(hwnd):
                    self.dismissed += 1
                    _logger.info(f"Dismissed the informational dialog {title!r}: {texts[:1]}")
            time.sleep(self.poll_seconds)

    def __enter__(self) -> dismiss_informational_dialog:
        if _user32() is not None:
            self._thread = threading.Thread(
                target=self._watch, name="dialog-dismisser", daemon=True
            )
            self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
