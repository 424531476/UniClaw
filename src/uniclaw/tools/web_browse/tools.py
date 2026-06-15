"""Web Browse 工具 — 基于 Playwright 的浏览器自动化操作。

提供导航、点击、输入、截图、执行 JS 等完整浏览器控制能力。
支持多页面(标签页)管理。
"""

from __future__ import annotations

from typing import Optional

from uniclaw.tools.base import tool
from .browser import WebBrowser

# 全局浏览器实例
_browser = WebBrowser()


# ── 浏览器生命周期 ────────────────────────────────────────────


@tool
async def browser_start(url: str, headless: bool = True) -> str:
    """启动浏览器并导航到指定 URL。默认使用无头模式,适合自动化任务。如需用户交互(如登录),可设置 headless=False 显示浏览器窗口。

    Args:
        url: 启动后立即导航到该 URL。
        headless: 是否使用无头模式,默认 True。设置为 False 可显示浏览器窗口。

    Returns:
        操作结果消息。
    """
    result = await _browser.start(headless=headless)
    nav_result = await _browser.navigate(url)
    return f"{result}\n{nav_result}"


@tool
async def browser_close() -> str:
    """关闭浏览器并释放所有页面。

    Returns:
        操作结果消息。
    """
    return await _browser.close()


# ── 页面管理 ──────────────────────────────────────────────────


@tool
async def browser_new_page() -> str:
    """创建新页面(标签页)并切换到该页面。

    Returns:
        操作结果消息,包含新页面 ID。
    """
    _, msg = await _browser.new_page()
    return msg


@tool
async def browser_close_page(page_id: int) -> str:
    """关闭指定页面。如果关闭的是活动页面,会自动切换到其他页面。

    Args:
        page_id: 要关闭的页面 ID。

    Returns:
        操作结果消息。
    """
    return await _browser.close_page(page_id)


@tool
async def browser_switch_page(page_id: int) -> str:
    """切换到指定页面。

    Args:
        page_id: 目标页面 ID。

    Returns:
        操作结果消息,包含页面标题。
    """
    return await _browser.switch_page(page_id)


@tool
async def browser_list_pages() -> str:
    """列出所有打开的页面,显示页面 ID、标题和 URL。

    Returns:
        页面列表信息。
    """
    return await _browser.list_pages()


# ── 页面操作 ──────────────────────────────────────────────────


@tool
async def browser_navigate(url: str, page_id: Optional[int] = None) -> str:
    """导航到指定 URL。

    Args:
        url: 要导航到的网页 URL。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息,包含页面标题。
    """
    return await _browser.navigate(url, page_id)


@tool
async def browser_click(selector: str, timeout: int = 5000, page_id: Optional[int] = None) -> str:
    """点击页面元素。

    Args:
        selector: CSS 选择器或 XPath 表达式(以 // 开头表示 XPath)。
        timeout: 等待元素出现的超时时间(毫秒),默认 5000。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.click(selector, timeout, page_id)


@tool
async def browser_type(selector: str, text: str, clear: bool = True, timeout: int = 5000, page_id: Optional[int] = None) -> str:
    """在指定元素中输入文本。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        text: 要输入的文本内容。
        clear: 是否先清空输入框,默认 True。
        timeout: 等待元素出现的超时时间(毫秒),默认 5000。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.type_text(selector, text, clear, timeout, page_id)


@tool
async def browser_screenshot(selector: Optional[str] = None, full_page: bool = False, save_path: Optional[str] = None, page_id: Optional[int] = None) -> list:
    """截取页面或指定元素的截图(仅用于查看页面效果,不要用于定位元素)。

    ⚠️ 如需点击、输入等操作,必须使用 browser_get_elements 获取精确选择器,不要通过截图猜测坐标。
    ⚠️ 如需获取页面文本内容,请使用 browser_get_text,不要用截图来"看"网页文字。

    Args:
        selector: 可选,CSS 选择器或 XPath 表达式,截取特定元素。不提供则截取整个页面。
        full_page: 是否截取完整页面(包括滚动区域),默认 False。
        save_path: 可选,截图保存的本地文件路径(如 "screenshot.png")。不提供则返回 base64 图片供 LLM 查看。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        包含截图的多模态内容列表,或保存成功的消息。
    """
    return await _browser.screenshot(selector, full_page, save_path, page_id)


@tool
async def browser_get_text(selector: Optional[str] = None, page_id: Optional[int] = None) -> str:
    """获取页面或指定元素的文本内容。

    Args:
        selector: 可选,CSS 选择器或 XPath 表达式。不提供则获取整个页面文本。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        文本内容。
    """
    return await _browser.get_text(selector, page_id)


@tool
async def browser_get_html(selector: Optional[str] = None, page_id: Optional[int] = None) -> str:
    """获取页面或指定元素的 HTML 内容。

    Args:
        selector: 可选,CSS 选择器或 XPath 表达式。不提供则获取整个页面 HTML。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        HTML 内容。
    """
    return await _browser.get_html(selector, page_id)


@tool
async def browser_get_attribute(selector: str, attribute: str, page_id: Optional[int] = None) -> str:
    """获取指定元素的属性值。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        attribute: 属性名称(如 href、src、value 等)。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        属性值。
    """
    return await _browser.get_attribute(selector, attribute, page_id)


@tool
async def browser_get_elements(page_id: Optional[int] = None) -> str:
    """获取页面上所有可交互元素的信息,可穿透付费墙等遮挡层(优先使用此工具而非截图)。

    ⚠️ 重要:在点击、输入等操作前,必须先调用此工具获取元素选择器,不要依赖截图猜测坐标。
    截图只能看到视觉效果,无法获取精确的元素选择器和属性信息。

    返回按钮、输入框、链接、下拉框等可交互元素的:
    - 标签、类型、id、name、文本内容
    - placeholder、href、role、aria-label 等属性
    - 推荐的 CSS 选择器(可直接用于 click/type 等操作)
    - 元素位置和尺寸

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        可交互元素列表,包含每个元素的选择器和属性信息。
    """
    return await _browser.get_interactive_elements(page_id)


@tool
async def browser_wait(selector: str, state: str = "visible", timeout: int = 10000, page_id: Optional[int] = None) -> str:
    """等待元素达到指定状态。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        state: 等待状态,可选值: "attached"(已附加)、"detached"(已分离)、"visible"(可见)、"hidden"(隐藏)。
        timeout: 超时时间(毫秒),默认 10000。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.wait_for(selector, state, timeout, page_id)


@tool
async def browser_evaluate(expression: str, page_id: Optional[int] = None) -> str:
    """在页面中执行 JavaScript 表达式并返回结果。

    Args:
        expression: 要执行的 JavaScript 表达式。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        执行结果。
    """
    return await _browser.evaluate(expression, page_id)


@tool
async def browser_scroll(direction: str = "down", amount: int = 500, page_id: Optional[int] = None) -> str:
    """滚动页面。

    Args:
        direction: 滚动方向,可选值: "up"(向上)、"down"(向下)。
        amount: 滚动像素量,默认 500。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.scroll(direction, amount, page_id)


@tool
async def browser_back(page_id: Optional[int] = None) -> str:
    """浏览器后退。

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.back(page_id)


@tool
async def browser_forward(page_id: Optional[int] = None) -> str:
    """浏览器前进。

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.forward(page_id)


@tool
async def browser_reload(page_id: Optional[int] = None) -> str:
    """刷新当前页面。

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.reload(page_id)


@tool
async def browser_get_url(page_id: Optional[int] = None) -> str:
    """获取当前页面 URL。

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        当前页面 URL。
    """
    return await _browser.get_url(page_id)


@tool
async def browser_get_title(page_id: Optional[int] = None) -> str:
    """获取当前页面标题。

    Args:
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        当前页面标题。
    """
    return await _browser.get_title(page_id)


@tool
async def browser_toggle_mode(headless: bool = True) -> str:
    """切换浏览器显示模式,保留所有页面 URL。

    当需要用户交互(如登录、验证码)时,可切换到有头模式(headless=False)显示浏览器窗口。
    交互完成后切换回无头模式(headless=True)继续自动化。

    Args:
        headless: True 为无头模式(隐藏窗口),False 为有头模式(显示窗口)。

    Returns:
        操作结果消息。
    """
    return await _browser.switch_mode(headless=headless)


@tool
async def browser_press_key(key: str, page_id: Optional[int] = None) -> str:
    """按下键盘按键。

    Args:
        key: 按键名称,如 "Enter"、"Tab"、"Escape"、"ArrowUp"、"ArrowDown" 等。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.press_key(key, page_id)


@tool
async def browser_select_option(selector: str, value: str, page_id: Optional[int] = None) -> str:
    """选择下拉框选项。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        value: 要选择的选项值。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.select_option(selector, value, page_id)


@tool
async def browser_check(selector: str, checked: bool = True, page_id: Optional[int] = None) -> str:
    """勾选或取消勾选复选框。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        checked: True 为勾选,False 为取消勾选。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.check(selector, checked, page_id)


@tool
async def browser_hover(selector: str, page_id: Optional[int] = None) -> str:
    """鼠标悬停在元素上。

    Args:
        selector: CSS 选择器或 XPath 表达式。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.hover(selector, page_id)


@tool
async def browser_drag(source: str, target: str, page_id: Optional[int] = None) -> str:
    """拖拽元素到目标位置。

    Args:
        source: 源元素的 CSS 选择器或 XPath 表达式。
        target: 目标元素的 CSS 选择器或 XPath 表达式。
        page_id: 可选,指定操作的页面 ID。不提供则使用当前活动页面。

    Returns:
        操作结果消息。
    """
    return await _browser.drag(source, target, page_id)


# ── 工具列表 ──────────────────────────────────────────────────

# 核心浏览器工具(常用)
CORE_BROWSE_TOOLS = [
    browser_start,
    browser_close,
    browser_navigate,
    browser_click,
    browser_type,
    browser_screenshot,
    browser_get_text,
    browser_get_elements,
    browser_evaluate,
]

# 页面管理工具
PAGE_MANAGEMENT_TOOLS = [
    browser_new_page,
    browser_close_page,
    browser_switch_page,
    browser_list_pages,
]

# 扩展浏览器工具
EXTENDED_BROWSE_TOOLS = [
    browser_get_html,
    browser_get_attribute,
    browser_wait,
    browser_scroll,
    browser_back,
    browser_forward,
    browser_reload,
    browser_get_url,
    browser_get_title,
    browser_toggle_mode,
    browser_press_key,
    browser_select_option,
    browser_check,
    browser_hover,
    browser_drag,
]


def get_tools() -> list:
    """获取 web browse 工具列表。"""
    return CORE_BROWSE_TOOLS + PAGE_MANAGEMENT_TOOLS + EXTENDED_BROWSE_TOOLS


def get_all_tools() -> list:
    """获取所有 web browse 工具。"""
    return get_tools()
