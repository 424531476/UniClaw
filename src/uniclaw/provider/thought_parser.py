"""流式解析 <thought>/<thinking> 标签。"""

from __future__ import annotations

from enum import Enum


class ThoughtParser:
    """流式解析 <thought>/<thinking> 标签。"""

    class Phase(Enum):
        SEEKING_OPEN = "seeking_open"
        IN_THOUGHT = "in_thought"
        TEXT = "text"

    def __init__(self):
        self.phase = self.Phase.SEEKING_OPEN
        self.buffer = ""
        self.close_tag = ""
        self.tags = ("<thought>", "</thought>"), ("<think>", "</think>")

    def process(self, text: str) -> tuple[str, str]:
        if self.phase == self.Phase.TEXT:
            return "", text
        text = self.buffer + text
        self.buffer = ""
        if self.phase == self.Phase.SEEKING_OPEN:
            return self._seeking_open(text)
        elif self.phase == self.Phase.IN_THOUGHT:
            return self._in_thought(text)

    def _seeking_open(self, text: str) -> tuple[str, str]:
        for open_tag, close_tag in self.tags:
            open_idx = text.find(open_tag)
            if open_idx < 0:
                continue
            self.phase = self.Phase.IN_THOUGHT
            self.close_tag = close_tag
            after = text[open_idx + len(open_tag) :]
            if after:
                return self.process(after)
        else:
            for open_tag, close_tag in self.tags:
                if open_tag.startswith(text):
                    self.buffer = text
                    return "", ""
            else:
                self.phase = self.Phase.TEXT
                return "", text

    def _in_thought(self, text: str) -> tuple[str, str]:
        close_tag = self.close_tag
        close_idx = text.find(close_tag)
        if close_idx >= 0:
            self.phase = self.Phase.TEXT
            thinking = text[:close_idx]
            context = text[close_idx + len(close_tag) :]
            return thinking, context
        else:
            for i in range(len(close_tag), 0, -1):
                if text.endswith(close_tag[:i]):
                    self.buffer = text
                    return "", ""
            else:
                return text, ""
