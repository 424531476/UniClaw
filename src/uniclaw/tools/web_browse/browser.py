"""WebBrowser 类 — 封装 Playwright 浏览器操作。

提供浏览器生命周期管理、页面导航、元素交互、截图等完整浏览器控制能力。
支持多页面(标签页)管理。
"""

from __future__ import annotations

import base64
from typing import Optional

from uniclaw.utils.constants import SYSTEM_PREFIX

# 延迟导入 playwright,避免启动时加载 greenlet DLL
_async_playwright = None


def _get_async_playwright():
    """延迟导入 async_playwright,失败时抛出 RuntimeError。"""
    global _async_playwright
    if _async_playwright is None:
        try:
            from playwright.async_api import async_playwright
            _async_playwright = async_playwright
        except ImportError as e:
            err_str = str(e).lower()
            if "greenlet" in err_str and "dll" in err_str:
                hint = (
                    "greenlet DLL 加载失败,缺少 Visual C++ 运行库。\n\n"
                    "修复方法(任选其一):\n"
                    "1. 安装 VC++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                    "2. uv pip install --force-reinstall greenlet"
                )
            elif "greenlet" in err_str:
                hint = (
                    "greenlet 模块损坏。\n\n"
                    "修复方法:\n"
                    "uv pip install --force-reinstall greenlet"
                )
            elif "playwright" in err_str:
                hint = (
                    "playwright 未安装。\n\n"
                    "修复方法:\n"
                    "uv sync && uv run playwright install chromium"
                )
            else:
                hint = (
                    f"Playwright 导入失败: {e}\n\n"
                    "修复方法:\n"
                    "1. uv pip install --force-reinstall greenlet\n"
                    "2. uv run playwright install chromium"
                )
            raise RuntimeError(hint) from e
    return _async_playwright


class WebBrowser:
    """封装 Playwright 浏览器实例,提供统一的浏览器操作接口。

    支持无头/有头模式切换,多页面管理,保持浏览器状态直到显式关闭。
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[int, object] = {}  # page_id -> page
        self._active_page_id: Optional[int] = None
        self._headless = True
        self._next_id = 1

    @property
    def is_running(self) -> bool:
        """浏览器是否正在运行。"""
        return self._browser is not None

    @property
    def headless(self) -> bool:
        """当前是否为无头模式。"""
        return self._headless

    @property
    def active_page(self):
        """获取当前活动页面。"""
        if self._active_page_id is None:
            return None
        return self._pages.get(self._active_page_id)

    @property
    def active_page_id(self) -> Optional[int]:
        """获取当前活动页面 ID。"""
        return self._active_page_id

    @property
    def page_ids(self) -> list[int]:
        """获取所有页面 ID 列表。"""
        return list(self._pages.keys())

    async def start(self, headless: bool = True) -> str:
        """启动浏览器。

        Args:
            headless: 是否使用无头模式。

        Returns:
            操作结果消息。
        """
        async_playwright_fn = _get_async_playwright()

        if self._browser is not None and self._headless != headless:
            await self.close()

        if self._browser is None:
            self._playwright = await async_playwright_fn().start()
            self._browser = await self._playwright.chromium.launch(headless=headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            # 创建默认页面
            await self.new_page()
            self._headless = headless

        mode = "无头模式" if headless else "有头模式"
        return f"浏览器已启动({mode}),页面 ID: {self._active_page_id}"

    async def close(self) -> str:
        """关闭浏览器并释放资源。"""
        if self._browser is None:
            return "浏览器未启动"

        try:
            for page in self._pages.values():
                await page.close()
            self._pages.clear()
            self._active_page_id = None

            if self._context:
                await self._context.close()
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            return "浏览器已关闭"
        except Exception as e:
            return f"关闭浏览器失败: {e}"

    async def new_page(self) -> tuple[int, str]:
        """创建新页面(标签页)。

        Returns:
            (page_id, 消息)
        """
        self._ensure_running()
        try:
            page = await self._context.new_page()
            page_id = self._next_id
            self._next_id += 1
            self._pages[page_id] = page
            self._active_page_id = page_id
            return page_id, f"已创建新页面,ID: {page_id}"
        except Exception as e:
            return -1, f"创建页面失败: {e}"

    async def close_page(self, page_id: int) -> str:
        """关闭指定页面。

        Args:
            page_id: 页面 ID。

        Returns:
            操作结果消息。
        """
        self._ensure_running()
        if page_id not in self._pages:
            return f"页面 {page_id} 不存在"

        try:
            page = self._pages[page_id]
            await page.close()
            del self._pages[page_id]

            # 如果关闭的是活动页面,切换到其他页面
            if self._active_page_id == page_id:
                if self._pages:
                    self._active_page_id = next(iter(self._pages))
                else:
                    self._active_page_id = None

            return f"已关闭页面 {page_id}"
        except Exception as e:
            return f"关闭页面失败: {e}"

    async def switch_page(self, page_id: int) -> str:
        """切换到指定页面。

        Args:
            page_id: 页面 ID。

        Returns:
            操作结果消息。
        """
        self._ensure_running()
        if page_id not in self._pages:
            return f"页面 {page_id} 不存在"

        self._active_page_id = page_id
        page = self._pages[page_id]
        title = await page.title()
        return f"已切换到页面 {page_id},标题: {title}"

    async def list_pages(self) -> str:
        """列出所有页面。

        Returns:
            页面列表信息。
        """
        self._ensure_running()
        if not self._pages:
            return "没有打开的页面"

        lines = ["打开的页面:"]
        for page_id, page in self._pages.items():
            try:
                title = await page.title()
                url = page.url
                active = " (活动)" if page_id == self._active_page_id else ""
                lines.append(f"  [{page_id}] {title} - {url}{active}")
            except Exception:
                lines.append(f"  [{page_id}] (无法获取信息)")

        return "\n".join(lines)

    async def navigate(self, url: str, page_id: Optional[int] = None) -> str:
        """导航到指定 URL。"""
        page = self._get_page(page_id)
        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=30000
            )
            title = await page.title()
            status = response.status if response else "未知"
            pid = page_id or self._active_page_id
            return f"已导航到: {url}\n页面标题: {title}\n状态码: {status}"
        except Exception as e:
            return f"导航失败: {e}"

    async def click(
        self, selector: str, timeout: int = 5000, page_id: Optional[int] = None
    ) -> str:
        """点击页面元素。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            await locator.click(timeout=timeout)
            return f"已点击元素: {selector}"
        except Exception as e:
            return f"点击失败: {e}"

    async def type_text(
        self,
        selector: str,
        text: str,
        clear: bool = True,
        timeout: int = 5000,
        page_id: Optional[int] = None,
    ) -> str:
        """在指定元素中输入文本。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            if clear:
                await locator.fill("", timeout=timeout)
            await locator.fill(text, timeout=timeout)
            return f"已在元素 {selector} 中输入文本"
        except Exception as e:
            return f"输入失败: {e}"

    async def screenshot(
        self,
        selector: Optional[str] = None,
        full_page: bool = False,
        page_id: Optional[int] = None,
    ) -> list:
        """截取页面或指定元素的截图。"""
        page = self._get_page(page_id)
        try:
            if selector:
                locator = self._get_locator(page, selector)
                screenshot_bytes = await locator.screenshot()
            else:
                screenshot_bytes = await page.screenshot(full_page=full_page)

            img_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            size_kb = len(screenshot_bytes) / 1024

            return [
                {
                    "type": "text",
                    "text": f"{SYSTEM_PREFIX}[浏览器截图: {size_kb:.0f} KB]",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                },
            ]
        except Exception as e:
            return [{"type": "text", "text": f"截图失败: {e}"}]

    async def get_text(
        self, selector: Optional[str] = None, page_id: Optional[int] = None
    ) -> str:
        """获取页面或指定元素的文本内容。"""
        page = self._get_page(page_id)
        try:
            if selector:
                locator = self._get_locator(page, selector)
                text = await locator.inner_text()
            else:
                text = await page.inner_text("body")
            if len(text) > 5000:
                return text[:5000] + f"\n\n...已省略 {len(text) - 5000} 个字符"
            return text
        except Exception as e:
            return f"获取文本失败: {e}"

    async def get_html(
        self, selector: Optional[str] = None, page_id: Optional[int] = None
    ) -> str:
        """获取页面或指定元素的 HTML 内容。"""
        page = self._get_page(page_id)
        try:
            if selector:
                locator = self._get_locator(page, selector)
                html = await locator.inner_html()
            else:
                html = await page.content()
            if len(html) > 5000:
                return html[:5000] + f"\n\n...已省略 {len(html) - 5000} 个字符"
            return html
        except Exception as e:
            return f"获取 HTML 失败: {e}"

    async def get_attribute(
        self, selector: str, attribute: str, page_id: Optional[int] = None
    ) -> str:
        """获取指定元素的属性值。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            value = await locator.get_attribute(attribute)
            return value if value else f"元素 {selector} 没有属性 {attribute}"
        except Exception as e:
            return f"获取属性失败: {e}"

    async def get_interactive_elements(self, page_id: Optional[int] = None) -> str:
        """获取页面上所有可交互元素的信息。

        返回按钮、输入框、链接、下拉框等可交互元素的标签、文本、属性和选择器。
        用于 AI 精确定位元素,避免依赖截图识别。
        """
        page = self._get_page(page_id)
        try:
            # 使用 JavaScript 获取所有可交互元素
            elements = await page.evaluate("""
                () => {
                    const selectors = [
                        'a[href]', 'button', 'input', 'select', 'textarea',
                        '[role="button"]', '[role="link"]', '[role="tab"]',
                        '[onclick]', '[tabindex]'
                    ];
                    const elements = document.querySelectorAll(selectors.join(','));
                    const result = [];
                    let index = 0;

                    for (const el of elements) {
                        // 跳过隐藏元素
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') {
                            continue;
                        }

                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) {
                            continue;
                        }

                        const tag = el.tagName.toLowerCase();
                        const type = el.getAttribute('type') || '';
                        const id = el.id || '';
                        const name = el.getAttribute('name') || '';
                        const className = el.className || '';
                        const href = el.getAttribute('href') || '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        const value = el.value || '';
                        const text = el.textContent?.trim().substring(0, 100) || '';
                        const role = el.getAttribute('role') || '';
                        const ariaLabel = el.getAttribute('aria-label') || '';

                        // 生成最佳选择器
                        let selector = '';
                        if (id) {
                            selector = '#' + CSS.escape(id);
                        } else if (name) {
                            selector = tag + '[name="' + name + '"]';
                        } else if (className && typeof className === 'string') {
                            const classes = className.split(/\\s+/).filter(c => c).slice(0, 2);
                            if (classes.length) {
                                selector = tag + '.' + classes.map(c => CSS.escape(c)).join('.');
                            }
                        }
                        if (!selector) {
                            selector = tag;
                        }

                        result.push({
                            index: index++,
                            tag,
                            type,
                            id,
                            name,
                            text: text.substring(0, 50),
                            placeholder,
                            href: href.substring(0, 100),
                            role,
                            ariaLabel,
                            selector,
                            rect: {
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            }
                        });
                    }

                    return result;
                }
            """)

            if not elements:
                return "页面上没有找到可交互元素"

            # 格式化输出
            lines = [f"找到 {len(elements)} 个可交互元素:\n"]
            for el in elements:
                parts = [f"[{el['index']}] <{el['tag']}>"]
                if el["type"]:
                    parts.append(f"type={el['type']}")
                if el["id"]:
                    parts.append(f"id={el['id']}")
                if el["name"]:
                    parts.append(f"name={el['name']}")
                if el["text"]:
                    parts.append(f"text=\"{el['text']}\"")
                if el["placeholder"]:
                    parts.append(f"placeholder=\"{el['placeholder']}\"")
                if el["href"]:
                    parts.append(f"href=\"{el['href']}\"")
                if el["role"]:
                    parts.append(f"role={el['role']}")
                if el["ariaLabel"]:
                    parts.append(f"aria=\"{el['ariaLabel']}\"")
                parts.append(f"selector={el['selector']}")
                parts.append(
                    f"pos=({el['rect']['x']},{el['rect']['y']}) {el['rect']['width']}x{el['rect']['height']}"
                )
                lines.append(" | ".join(parts))

            result = "\n".join(lines)
            if len(result) > 50000:
                return result[:50000] + f"\n\n...已省略 {len(result) - 50000} 个字符"
            return result
        except Exception as e:
            return f"获取元素失败: {e}"

    async def wait_for(
        self,
        selector: str,
        state: str = "visible",
        timeout: int = 10000,
        page_id: Optional[int] = None,
    ) -> str:
        """等待元素达到指定状态。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            await locator.wait_for(state=state, timeout=timeout)
            return f"元素 {selector} 已达到状态: {state}"
        except Exception as e:
            return f"等待元素失败: {e}"

    async def evaluate(self, expression: str, page_id: Optional[int] = None) -> str:
        """在页面中执行 JavaScript 表达式并返回结果。"""
        page = self._get_page(page_id)
        try:
            result = await page.evaluate(expression)
            return str(result) if result is not None else "执行成功(无返回值)"
        except Exception as e:
            return f"执行 JavaScript 失败: {e}"

    async def scroll(
        self, direction: str = "down", amount: int = 500, page_id: Optional[int] = None
    ) -> str:
        """滚动页面。"""
        page = self._get_page(page_id)
        try:
            delta = amount if direction == "down" else -amount
            await page.mouse.wheel(0, delta)
            direction_cn = "下" if direction == "down" else "上"
            return f"已向{direction_cn}滚动 {amount} 像素"
        except Exception as e:
            return f"滚动失败: {e}"

    async def back(self, page_id: Optional[int] = None) -> str:
        """浏览器后退。"""
        page = self._get_page(page_id)
        try:
            await page.go_back()
            title = await page.title()
            return f"已后退,当前页面: {title}"
        except Exception as e:
            return f"后退失败: {e}"

    async def forward(self, page_id: Optional[int] = None) -> str:
        """浏览器前进。"""
        page = self._get_page(page_id)
        try:
            await page.go_forward()
            title = await page.title()
            return f"已前进,当前页面: {title}"
        except Exception as e:
            return f"前进失败: {e}"

    async def reload(self, page_id: Optional[int] = None) -> str:
        """刷新当前页面。"""
        page = self._get_page(page_id)
        try:
            await page.reload()
            title = await page.title()
            return f"已刷新页面: {title}"
        except Exception as e:
            return f"刷新失败: {e}"

    async def get_url(self, page_id: Optional[int] = None) -> str:
        """获取当前页面 URL。"""
        page = self._get_page(page_id)
        return f"当前 URL: {page.url}"

    async def get_title(self, page_id: Optional[int] = None) -> str:
        """获取当前页面标题。"""
        page = self._get_page(page_id)
        try:
            title = await page.title()
            return f"页面标题: {title}"
        except Exception as e:
            return f"获取标题失败: {e}"

    async def switch_mode(self, headless: bool) -> str:
        """切换浏览器模式,保留所有页面 URL 和登录状态。

        通过 storage_state 保存和恢复 cookie、localStorage 等状态。

        Args:
            headless: True 为无头模式(隐藏窗口),False 为有头模式(显示窗口)。

        Returns:
            操作结果消息。
        """
        if self._browser is None:
            return "浏览器未启动"
        if self._headless == headless:
            return f"浏览器已在{'无头' if headless else '有头'}模式"

        # 保存所有页面的 URL
        page_urls = {pid: page.url for pid, page in self._pages.items()}

        # 保存浏览器状态(cookie、localStorage 等)
        storage_state = await self._context.storage_state()

        await self.close()
        await self.start(headless=headless)

        # 恢复 cookie
        await self._context.add_cookies(storage_state.get("cookies", []))

        # 构建 origin -> localStorage 映射
        origin_storage = {}
        for origin in storage_state.get("origins", []):
            origin_url = origin.get("origin", "")
            local_storage = origin.get("localStorage", [])
            if origin_url and local_storage:
                origin_storage[origin_url] = local_storage

        # 恢复页面,并在导航后恢复对应 origin 的 localStorage
        first = True
        for url in page_urls.values():
            if first:
                page = self.active_page
                first = False
            else:
                _, _ = await self.new_page()
                page = self.active_page

            if url and url != "about:blank":
                await page.goto(url, wait_until="domcontentloaded")
                # 恢复该 origin 的 localStorage
                from urllib.parse import urlparse

                parsed = urlparse(url)
                origin_key = f"{parsed.scheme}://{parsed.netloc}"
                if origin_key in origin_storage:
                    for item in origin_storage[origin_key]:
                        key = item.get("key", "")
                        value = item.get("value", "")
                        if key:
                            await page.evaluate(
                                f"localStorage.setItem({key!r}, {value!r})"
                            )

        return f"已切换到{'无头' if headless else '有头'}模式"

    async def press_key(self, key: str, page_id: Optional[int] = None) -> str:
        """按下键盘按键。"""
        page = self._get_page(page_id)
        try:
            await page.keyboard.press(key)
            return f"已按下按键: {key}"
        except Exception as e:
            return f"按键失败: {e}"

    async def select_option(
        self, selector: str, value: str, page_id: Optional[int] = None
    ) -> str:
        """选择下拉框选项。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            await locator.select_option(value)
            return f"已选择选项: {value}"
        except Exception as e:
            return f"选择选项失败: {e}"

    async def check(
        self, selector: str, checked: bool = True, page_id: Optional[int] = None
    ) -> str:
        """勾选或取消勾选复选框。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            await locator.check() if checked else await locator.uncheck()
            action = "勾选" if checked else "取消勾选"
            return f"已{action}元素: {selector}"
        except Exception as e:
            return f"操作失败: {e}"

    async def hover(self, selector: str, page_id: Optional[int] = None) -> str:
        """鼠标悬停在元素上。"""
        page = self._get_page(page_id)
        try:
            locator = self._get_locator(page, selector)
            await locator.hover()
            return f"已悬停在元素: {selector}"
        except Exception as e:
            return f"悬停失败: {e}"

    async def drag(
        self, source: str, target: str, page_id: Optional[int] = None
    ) -> str:
        """拖拽元素到目标位置。"""
        page = self._get_page(page_id)
        try:
            source_locator = self._get_locator(page, source)
            target_locator = self._get_locator(page, target)
            await source_locator.drag_to(target_locator)
            return f"已将 {source} 拖拽到 {target}"
        except Exception as e:
            return f"拖拽失败: {e}"

    def _get_page(self, page_id: Optional[int] = None):
        """获取指定页面,未指定则返回活动页面。"""
        self._ensure_running()
        if page_id is None:
            page = self.active_page
            if page is None:
                raise RuntimeError("没有活动页面")
            return page
        if page_id not in self._pages:
            raise RuntimeError(f"页面 {page_id} 不存在")
        return self._pages[page_id]

    def _ensure_running(self):
        """确保浏览器已启动,否则抛出异常。"""
        if self._browser is None:
            raise RuntimeError("浏览器未启动,请先调用 browser_start")

    def _get_locator(self, page, selector: str):
        """根据选择器类型获取 locator。"""
        if selector.startswith("//"):
            return page.locator(f"xpath={selector}")
        return page.locator(selector)
