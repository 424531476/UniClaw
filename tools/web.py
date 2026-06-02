import re
import httpx
from langchain_core.tools import tool


@tool
def webFetch(url: str, max_length: int = 25000) -> str:
    """
    从指定的URL获取网页内容并提取纯文本。

    该函数会发送HTTP GET请求获取网页内容,如果内容是HTML格式,
    则会移除script和style标签,并清理所有HTML标签,最终返回纯文本内容。
    返回的文本长度可通过max_length参数控制。

    Args:
        url (str): 要获取内容的网页URL地址
        max_length (int): 返回文本的最大长度,默认为25000字符

    Returns:
        str: 提取的纯文本内容(最多max_length个字符),如果发生错误则返回错误信息字符串

    Raises:
        ImportError: 当httpx库未安装时捕获并返回安装提示
        Exception: 捕获其他所有异常并返回错误信息
    """
    try:
        # 发送HTTP GET请求获取网页内容
        r = httpx.get(
            url,
            headers={"User-Agent": "NanoClaude/1.0"},
            timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()

        # 检查响应内容类型,判断是否为HTML
        ct = r.headers.get("content-type", "")
        text = r.text
        if "html" in ct:
            # 移除HTML中的script和style标签及其内容
            text = re.sub(
                r"<script[^>]*>.*?</script>",
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            # 移除所有HTML标签并清理多余空白字符
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        # 限制返回文本长度为max_length个字符
        return text[:max_length]
    except ImportError:
        return "Error: httpx not installed — run: pip install httpx"
    except Exception as e:
        return f"Error: {e}"


@tool
def webSearch(query: str) -> str:
    """
    执行网络搜索并返回格式化的搜索结果。

    使用 DuckDuckGo 搜索引擎进行搜索,提取标题、链接和摘要信息,
    并以 Markdown 格式返回最多8条搜索结果。

    Args:
        query (str): 搜索查询字符串

    Returns:
        str: 格式化的搜索结果,每条结果包含标题(加粗)、链接和摘要,
             结果之间用双换行分隔。如果未找到结果则返回 "No results found",
             如果发生错误则返回错误信息。
    """
    try:

        url = "https://html.duckduckgo.com/html/"
        
        # 配置代理设置并使用 Client 发送请求
        from config import load_config
        proxy_url = load_config().get("proxy_url")
        with httpx.Client(proxy=proxy_url) as client:
            r = client.get(
                url,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible)"},
                timeout=30,
                follow_redirects=True,
            )

        # 从搜索结果页面提取标题和链接
        titles = re.findall(
            r'class="result__title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            r.text,
            re.DOTALL,
        )

        # 从搜索结果页面提取摘要信息
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</div>',
            r.text,
            re.DOTALL,
        )

        # 格式化前8条搜索结果
        results = []
        for i, (link, title) in enumerate(titles[:8]):
            t = re.sub(r"<[^>]+>", "", title).strip()
            s = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
            results.append(f"**{t}**\n{link}\n{s}")
        return "\n\n".join(results) if results else "No results found"
    except ImportError:
        return "Error: httpx not installed — run: pip install httpx"
    except Exception as e:
        return f"Error: {e}"


def get_tools() -> list:
    """获取Web工具列表"""
    return [webFetch, webSearch]


def get_all_tools() -> list:
    """获取所有Web工具(无条件返回)"""
    return get_tools()