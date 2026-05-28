"""Computer Use 工具 - 提供屏幕截图、鼠标和键盘控制功能"""

import base64
import io
import time
import threading
from typing import Optional

import mss
import pyautogui
from langchain_core.tools import tool
from PIL import Image, ImageDraw

# 禁用 pyautogui 的安全暂停和故障保护(在受控环境中使用)
pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True


def get_cu_system_prompt() -> str:
    """返回 Computer Use 模式的系统提示词,包含核心工作流程和使用说明。"""
    if not is_enabled():
        return ""
    return f"""
# Computer Use 模式
你现在拥有完整的计算机控制能力,可以直接操作鼠标、键盘和屏幕。

## 核心工作流程
1. 用 `{screenshot.name}` 截取屏幕,了解当前状态和坐标
2. 分析截图中目标元素的精确坐标位置
3. 使用鼠标/键盘工具执行操作
4. 再次截图验证操作是否成功,失败则调整坐标重试

## 关键规则
- **截图是唯一视觉来源**:无法"记住"位置,每次都要重新截图
- **点击前后必须截图**:确认坐标后再点击,点击后验证结果
- 截图上的红色十字标记是当前鼠标位置,利用它定位和调整坐标
- 不要假设屏幕分辨率,以截图中显示的实际分辨率为准

## 操作提示
- 坐标系统:左上角 (0,0),向右为 x+,向下为 y+
- 点击:先 `{mouse_move.name}` 移动,再 `{mouse_click.name}` 点击
- 输入英文用 `{keyboard_type.name}`,输入中文用 `{keyboard_type_unicode.name}`
- 组合键:`{keyboard_press.name}("ctrl+c")`
- 等待响应:`{wait.name}(seconds=1)`

## 坐标定位技巧
不确定坐标时使用"试探法":
1. 估算坐标 → `{mouse_move.name}` 移动鼠标 → `{screenshot.name}` 截图
2. 观察十字标记与目标的距离,增减 x/y 坐标
3. 重复移动-截图-调整,直到十字标记精确对准目标中心再点击
"""


class _ComputerUseState:
    """管理 computer use 的启用/禁用状态"""

    def __init__(self):
        self._enabled = False
        self._lock = threading.Lock()
        self._hotkey_registered = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def enable(self) -> bool:
        with self._lock:
            if self._enabled:
                return False
            self._enabled = True
            return True

    def disable(self) -> bool:
        with self._lock:
            if not self._enabled:
                return False
            self._enabled = False
            return True

    def toggle(self) -> bool:
        with self._lock:
            self._enabled = not self._enabled
            return self._enabled


_state = _ComputerUseState()
_hotkey_listener = None


def is_enabled() -> bool:
    """检查 computer use 是否已启用"""
    return _state.enabled


def enable_computer_use() -> bool:
    """启用 computer use"""
    return _state.enable()


def disable_computer_use() -> bool:
    """禁用 computer use"""
    return _state.disable()


def toggle_computer_use() -> bool:
    """切换 computer use 状态"""
    result = _state.toggle()
    # 刷新 TUI 状态栏
    try:
        from console.run import TUIApp

        app = TUIApp.get_instance()
        if app and app.app:
            app.app.invalidate()
    except Exception:
        pass
    return result


def register_global_hotkey() -> bool:
    """注册系统级全局快捷键 Ctrl+U 切换 Computer Use(跨平台 pynput)"""
    global _hotkey_listener
    if _state._hotkey_registered:
        return True

    try:
        from pynput import keyboard

        def _on_activate():
            toggle_computer_use()

        hotkey = keyboard.HotKey(
            keyboard.HotKey.parse("<ctrl>+u"),
            _on_activate,
        )

        def _on_press(key):
            hotkey.press(listener.canonical(key))

        def _on_release(key):
            hotkey.release(listener.canonical(key))

        listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        listener.daemon = True
        listener.start()
        _hotkey_listener = listener
        _state._hotkey_registered = True
        return True
    except Exception:
        return False


def unregister_global_hotkey():
    """注销系统级全局快捷键"""
    global _hotkey_listener
    if _hotkey_listener is not None:
        try:
            _hotkey_listener.stop()
        except Exception:
            pass
        _hotkey_listener = None
        _state._hotkey_registered = False


@tool
def screenshot(region: Optional[str] = None) -> list:
    """截取屏幕截图并返回图像数据供 LLM 分析。截图上会标记当前鼠标位置。

    Args:
        region: 可选的截图区域,格式为 "x,y,width,height"(如 "100,200,800,600")。
                如果不提供,则截取整个屏幕。

    Returns:
        包含图像的多模态内容列表。
    """
    with mss.mss() as sct:
        if region:
            try:
                x, y, w, h = map(int, region.split(","))
                monitor = {"left": x, "top": y, "width": w, "height": h}
            except ValueError:
                return [
                    {
                        "type": "text",
                        "text": "错误:区域格式无效,请使用 'x,y,width,height' 格式",
                    }
                ]
        else:
            monitor = sct.monitors[0]  # 整个屏幕

        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # 获取鼠标位置并绘制标记
        cursor_x, cursor_y = pyautogui.position()
        draw = ImageDraw.Draw(img)

        # 计算相对坐标(如果指定了区域)
        if region:
            rel_x = cursor_x - monitor["left"]
            rel_y = cursor_y - monitor["top"]
        else:
            rel_x = cursor_x
            rel_y = cursor_y

        # 绘制十字标记
        cross_size = 20
        cross_color = (255, 0, 0)  # 红色
        cross_width = 3

        # 水平线
        draw.line(
            [(rel_x - cross_size, rel_y), (rel_x + cross_size, rel_y)],
            fill=cross_color,
            width=cross_width,
        )
        # 垂直线
        draw.line(
            [(rel_x, rel_y - cross_size), (rel_x, rel_y + cross_size)],
            fill=cross_color,
            width=cross_width,
        )
        # 中心圆点
        circle_size = 5
        draw.ellipse(
            [
                (rel_x - circle_size, rel_y - circle_size),
                (rel_x + circle_size, rel_y + circle_size),
            ],
            fill=cross_color,
        )

        # 转换为 base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        size_kb = buffer.getbuffer().nbytes / 1024
        img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return [
            {
                "type": "text",
                "text": f"[屏幕截图: {screenshot.width}x{screenshot.height}, {size_kb:.0f} KB | 鼠标位置: ({cursor_x}, {cursor_y})]",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_base64}"},
            },
        ]


@tool
def mouse_move(x: int, y: int, duration: float = 0.5) -> str:
    """移动鼠标到指定位置。

    Args:
        x: 目标位置的 x 坐标。
        y: 目标位置的 y 坐标。
        duration: 移动耗时(秒),默认 0.5 秒。

    Returns:
        操作结果消息。
    """
    pyautogui.moveTo(x, y, duration=duration)
    return f"鼠标已移动到 ({x}, {y})"


@tool
def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> str:
    """在指定位置点击鼠标。

    Args:
        x: 点击位置的 x 坐标。
        y: 点击位置的 y 坐标。
        button: 鼠标按钮,可选 "left"、"right"、"middle",默认 "left"。
        clicks: 点击次数,默认 1。设为 2 可双击。
        interval: 多次点击之间的间隔(秒),默认 0.1。

    Returns:
        操作结果消息。
    """
    pyautogui.click(x, y, clicks=clicks, button=button, interval=interval)
    action = "双击" if clicks == 2 else "点击"
    return f"已在 ({x}, {y}) {action}鼠标{button}键"


@tool
def mouse_double_click(x: int, y: int, button: str = "left") -> str:
    """在指定位置双击鼠标。

    Args:
        x: 点击位置的 x 坐标。
        y: 点击位置的 y 坐标。
        button: 鼠标按钮,可选 "left"、"right"、"middle",默认 "left"。

    Returns:
        操作结果消息。
    """
    pyautogui.doubleClick(x, y, button=button)
    return f"已在 ({x}, {y}) 双击鼠标{button}键"


@tool
def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
    button: str = "left",
) -> str:
    """拖拽鼠标从起始位置到结束位置。

    Args:
        start_x: 起始位置的 x 坐标。
        start_y: 起始位置的 y 坐标。
        end_x: 结束位置的 x 坐标。
        end_y: 结束位置的 y 坐标。
        duration: 拖拽耗时(秒),默认 0.5。
        button: 鼠标按钮,可选 "left"、"right"、"middle",默认 "left"。

    Returns:
        操作结果消息。
    """
    pyautogui.moveTo(start_x, start_y)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
    return f"已从 ({start_x}, {start_y}) 拖拽到 ({end_x}, {end_y})"


@tool
def mouse_scroll(clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> str:
    """滚动鼠标滚轮。

    Args:
        clicks: 滚动量。正数向上滚动,负数向下滚动。
        x: 可选,滚动位置的 x 坐标。不提供则在当前位置滚动。
        y: 可选,滚动位置的 y 坐标。不提供则在当前位置滚动。

    Returns:
        操作结果消息。
    """
    if x is not None and y is not None:
        pyautogui.scroll(clicks, x=x, y=y)
        return f"已在 ({x}, {y}) 滚动 {clicks} 格"
    else:
        pyautogui.scroll(clicks)
        direction = "上" if clicks > 0 else "下"
        return f"已向{direction}滚动 {abs(clicks)} 格"


@tool
def keyboard_type(text: str, interval: float = 0.05) -> str:
    """模拟键盘输入英文文本。仅支持 ASCII 字符,不要传入中文或其他非 ASCII 字符。

    Args:
        text: 要输入的文本内容。只允许英文、数字和常见符号。如需输入中文,请使用 keyboard_type_unicode。
        interval: 按键之间的间隔(秒),默认 0.05。

    Returns:
        操作结果消息。
    """
    pyautogui.typewrite(text, interval=interval)
    return f"已输入文本:{text}"


@tool
def keyboard_type_unicode(text: str, interval: float = 0.05) -> str:
    """模拟键盘输入 Unicode 文本(支持中文等非 ASCII 字符)。

    Args:
        text: 要输入的文本内容。
        interval: 按键之间的间隔(秒),默认 0.05。

    Returns:
        操作结果消息。
    """
    for char in text:
        pyautogui.write(char, interval=interval)
    return f"已输入 Unicode 文本:{text}"


@tool
def keyboard_press(keys: str) -> str:
    """按下键盘按键或组合键。

    Args:
        keys: 按键名称,多个按键用 '+' 连接表示组合键。
              常用按键:enter, tab, escape, space, backspace, delete,
              up, down, left, right, home, end, pageup, pagedown,
              f1-f12, ctrl, alt, shift, win。
              示例:"ctrl+c"(复制)、"alt+tab"(切换窗口)、"enter"(回车)。

    Returns:
        操作结果消息。
    """
    key_list = [k.strip() for k in keys.split("+")]
    pyautogui.hotkey(*key_list)
    return f"已按下按键:{keys}"


@tool
def keyboard_key_down(key: str) -> str:
    """按下并保持键盘按键。

    Args:
        key: 按键名称,如 "shift"、"ctrl"、"alt"。

    Returns:
        操作结果消息。
    """
    pyautogui.keyDown(key)
    return f"已按下并保持:{key}"


@tool
def keyboard_key_up(key: str) -> str:
    """释放键盘按键。

    Args:
        key: 按键名称,如 "shift"、"ctrl"、"alt"。

    Returns:
        操作结果消息。
    """
    pyautogui.keyUp(key)
    return f"已释放按键:{key}"


@tool
def wait(seconds: float) -> str:
    """等待指定的秒数。

    Args:
        seconds: 等待的秒数。

    Returns:
        操作结果消息。
    """
    time.sleep(seconds)
    return f"已等待 {seconds} 秒"


@tool
def locate_on_screen(image_path: str, confidence: float = 0.8) -> str:
    """在屏幕上查找指定图像的位置。

    Args:
        image_path: 要查找的图像文件路径。
        confidence: 匹配置信度,范围 0-1,默认 0.8。

    Returns:
        找到的图像中心坐标,或未找到的错误消息。
    """
    try:
        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
        if location:
            center = pyautogui.center(location)
            return f"找到图像,中心位置:({center.x}, {center.y})"
        else:
            return "未在屏幕上找到指定图像"
    except Exception as e:
        return f"查找图像时出错:{str(e)}"


# 只读工具(安全,始终可用)
READONLY_TOOLS = [
    screenshot,
    locate_on_screen,
    wait,
]

# 写入工具(需要启用 computer use 才可用)
WRITE_TOOLS = [
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_drag,
    mouse_scroll,
    keyboard_type,
    keyboard_type_unicode,
    keyboard_press,
    keyboard_key_down,
    keyboard_key_up,
]


def get_tools() -> list:
    """获取 computer use 工具列表(根据启用状态返回)"""
    if is_enabled():
        return READONLY_TOOLS + WRITE_TOOLS
    return READONLY_TOOLS


def get_all_tools() -> list:
    """获取所有 computer use 工具"""
    return READONLY_TOOLS + WRITE_TOOLS
