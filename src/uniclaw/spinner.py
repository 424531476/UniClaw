"""旋转器抽象基类 — 定义各 UI 共享的等待指示器接口。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod


class BaseSpinner(ABC):
    """旋转器抽象基类。

    所有 UI (TUI/WebUI/Client) 的旋转器都应继承此类,
    确保子代理能通过 config.spinner 共享同一实例。
    """

    @abstractmethod
    def start(self, text: str = "waiting...", wait_id: str | None = None) -> str:
        """开始旋转,返回 wait_id。"""

    @abstractmethod
    def stop(self, wait_id: str) -> None:
        """停止指定 wait_id 的旋转。"""

    @abstractmethod
    def is_active(self) -> bool:
        """是否有正在进行的旋转。"""

    @abstractmethod
    def get_display(self) -> str:
        """获取当前旋转器显示文本。"""


class NoopSpinner(BaseSpinner):
    """空旋转器 — 不产生任何输出,适用于微信/无 UI 等场景。"""

    def __init__(self):
        self._active_count = 0

    def start(self, text: str = "waiting...", wait_id: str | None = None) -> str:
        if wait_id is None:
            wait_id = f"NoopSpinner_{uuid.uuid4().hex[:8]}"
        self._active_count += 1
        return wait_id

    def stop(self, wait_id: str) -> None:
        if self._active_count > 0:
            self._active_count -= 1

    def is_active(self) -> bool:
        return self._active_count > 0

    def get_display(self) -> str:
        return ""
