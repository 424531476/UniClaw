import re
import httpx
from langchain_core.tools import tool
from cachetools import TTLCache

# 搜索结果缓存：64 条,5 分钟过期
_search_cache = TTLCache(maxsize=64, ttl=300)


def _get_proxy(config: dict | None) -> str | None:
    """从 config 中提取有效的代理地址,无效则返回 None。"""
    if not isinstance(config, dict):
        return None
    proxy = config.get("proxy_url", "")
    return proxy if isinstance(proxy, str) and proxy.startswith("http") else None


def _search_bing(query: str, max_results: int = 8) -> list[dict]:
    """Bing 搜索(国内直连,无需代理)。"""
    url = "https://www.bing.com/search"
    r = httpx.get(
        url,
        params={"q": query, "count": str(max_results)},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        timeout=15,
        follow_redirects=True,
    )
    r.raise_for_status()

    results = []
    # 提取搜索结果块
    blocks = re.findall(
        r'<li class="b_algo"[^>]*>(.*?)</li>',
        r.text,
        re.DOTALL,
    )
    for block in blocks[:max_results]:
        # 从 h2 > a 提取标题和链接(最可靠)
        h2_m = re.search(
            r'<h2[^>]*>.*?<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        if not h2_m:
            continue
        link = h2_m.group(1)
        title = re.sub(r"<[^>]+>", "", h2_m.group(2)).strip()
        # 提取摘要：优先 <p>,其次 <div class="b_caption"><p>
        snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = re.sub(r"<[^>]+>", "", snippet_m.group(1)).strip() if snippet_m else ""
        results.append({"title": title, "link": link, "snippet": snippet})
    return results


def _search_ddg(query: str, proxy: str | None, max_results: int = 8) -> list[dict]:
    """DuckDuckGo 搜索(国内需要代理)。"""
    url = "https://html.duckduckgo.com/html/"
    client_kwargs = {"proxy": proxy} if proxy else {}
    with httpx.Client(**client_kwargs, timeout=15) as client:
        r = client.get(
            url,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
            follow_redirects=True,
        )
    r.raise_for_status()

    titles = re.findall(
        r'class="result__title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        r.text,
        re.DOTALL,
    )
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</div>',
        r.text,
        re.DOTALL,
    )

    results = []
    for i, (link, title) in enumerate(titles[:max_results]):
        t = re.sub(r"<[^>]+>", "", title).strip()
        s = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
        results.append({"title": t, "link": link, "snippet": s})
    return results


@tool
def webFetch(url: str, max_length: int = 25000, config: dict = None) -> str:
    """
    从指定的URL获取网页内容并提取纯文本。

    该函数会发送HTTP GET请求获取网页内容,如果内容是HTML格式,
    则会移除script和style标签,并清理所有HTML标签,最终返回纯文本内容。
    返回的文本长度可通过max_length参数控制。

    Args:
        url (str): 要获取内容的网页URL地址
        max_length (int): 返回文本的最大长度,默认为25000字符
        config (dict): 内部使用参数,由系统自动注入,请勿传递。

    Returns:
        str: 提取的纯文本内容(最多max_length个字符),如果发生错误则返回错误信息字符串
    """
    try:
        proxy = _get_proxy(config)
        client_kwargs = {"proxy": proxy} if proxy else {}

        with httpx.Client(**client_kwargs, timeout=30) as client:
            r = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
                follow_redirects=True,
            )
        r.raise_for_status()

        ct = r.headers.get("content-type", "")
        text = r.text

        if "json" in ct:
            return text[:max_length]

        if "html" in ct:
            text = re.sub(
                r"<script[^>]*>.*?</script>",
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        return text[:max_length]
    except ImportError:
        return "错误: httpx 未安装,请运行: pip install httpx"
    except Exception as e:
        return f"错误: {e}"


@tool
def webSearch(query: str, config: dict = None) -> str:
    """
    执行网络搜索并返回格式化的搜索结果。

    优先使用 Bing 搜索(国内直连),失败时尝试 DuckDuckGo(需代理)。
    结果自动缓存 5 分钟。

    Args:
        query (str): 搜索查询字符串
        config (dict): 内部使用参数,由系统自动注入,请勿传递。

    Returns:
        str: 格式化的搜索结果,每条结果包含标题、链接和摘要
    """
    # 检查缓存
    cached = _search_cache.get(query)
    if cached is not None:
        return cached

    proxy = _get_proxy(config)
    raw_results = []
    errors = []

    # 1. 先尝试 Bing(国内直连)
    try:
        raw_results = _search_bing(query)
    except Exception as e:
        errors.append(f"Bing: {e}")

    # 2. Bing 失败 → 尝试 DuckDuckGo
    if not raw_results:
        try:
            raw_results = _search_ddg(query, proxy)
        except Exception as e:
            errors.append(f"DuckDuckGo: {e}")

    # 3. 都失败
    if not raw_results:
        return "未找到搜索结果" + (f" ({'; '.join(errors)})" if errors else "")

    # 格式化输出
    lines = []
    for r in raw_results[:8]:
        lines.append(f"**{r['title']}**\n{r['link']}\n{r['snippet']}")
    result = "\n\n".join(lines)

    # 写入缓存
    _search_cache[query] = result
    return result


def get_tools() -> list:
    """获取Web工具列表"""
    return [webFetch, webSearch]


def get_all_tools() -> list:
    """获取所有Web工具(无条件返回)"""
    return get_tools()
