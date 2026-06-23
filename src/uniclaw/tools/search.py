"""平台搜索工具 — 支持 GitHub / arXiv / Stack Overflow / Hacker News / X / 微博 / 知乎 / 抖音 / B站"""

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
from cachetools import TTLCache

from uniclaw.config import AppConfig
from uniclaw.tools.base import tool
from uniclaw.utils.constants import TOOL_ERROR

# 搜索结果缓存: 128 条, 10 分钟过期
_search_cache = TTLCache(maxsize=128, ttl=600)

# ── 辅助 ────────────────────────────────────────────────────


def _get_proxy(config: AppConfig | None) -> str | None:
    """从 config 中提取有效的代理地址,无效则返回 None。"""
    if config is None:
        return None
    proxy = config.proxy_url
    return proxy if isinstance(proxy, str) and proxy.startswith("http") else None


def _cache_key(query: str, platform: str, **kwargs) -> str:
    """构建缓存 key。"""
    parts = [query, platform]
    for k, v in sorted(kwargs.items()):
        if v:
            parts.append(f"{k}={v}")
    return "|".join(parts)


# ── 平台搜索实现 ────────────────────────────────────────────


async def _search_github(
    query: str, limit: int, sort: str, search_type: str, config: AppConfig | None
) -> str:
    """GitHub 搜索。"""
    st = search_type if search_type in ("repositories", "code", "issues", "users") else "repositories"
    s = sort if sort in ("stars", "forks", "updated", "best-match") else "stars"
    url = f"https://api.github.com/search/{st}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = getattr(config, "GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        r = await client.get(url, params={"q": query, "sort": s, "per_page": limit}, headers=headers)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        return "GitHub: 无搜索结果"
    lines = [f"**GitHub 搜索结果** ({st}, {len(items)} 条):\n"]
    for item in items:
        if st == "repositories":
            name = item.get("full_name", "")
            desc = item.get("description", "") or ""
            stars = item.get("stargazers_count", 0)
            lang = item.get("language", "") or ""
            link = item.get("html_url", "")
            lines.append(f"**{name}** ⭐{stars} [{lang}]")
            lines.append(f"  {desc}")
            lines.append(f"  {link}\n")
        elif st == "code":
            name = item.get("name", "")
            path = item.get("path", "")
            repo = item.get("repository", {}).get("full_name", "")
            link = item.get("html_url", "")
            lines.append(f"**{name}** ({path})")
            lines.append(f"  仓库: {repo}")
            lines.append(f"  {link}\n")
        elif st == "issues":
            title = item.get("title", "")
            state = item.get("state", "")
            link = item.get("html_url", "")
            lines.append(f"**{title}** [{state}]")
            lines.append(f"  {link}\n")
        else:  # users
            login = item.get("login", "")
            desc = item.get("bio", "") or ""
            link = item.get("html_url", "")
            lines.append(f"**{login}** — {desc}")
            lines.append(f"  {link}\n")
    return "\n".join(lines)


async def _search_arxiv(
    query: str, limit: int, sort: str, config: AppConfig | None
) -> str:
    """arXiv 搜索。"""
    s = sort if sort in ("relevance", "lastUpdatedDate", "submittedDate") else "relevance"
    url = "http://export.arxiv.org/api/query"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        r = await client.get(url, params={"search_query": f"all:{query}", "max_results": limit, "sortBy": s, "sortOrder": "descending"})
    r.raise_for_status()
    root = ET.fromstring(r.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        return "arXiv: 无搜索结果"
    lines = [f"**arXiv 搜索结果** ({len(entries)} 篇):\n"]
    for entry in entries:
        title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
        authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
        summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")[:200]
        link = entry.find("atom:id", ns).text.strip()
        published = entry.find("atom:published", ns).text[:10]
        lines.append(f"**{title}**")
        lines.append(f"  作者: {', '.join(authors[:3])}")
        lines.append(f"  日期: {published}")
        lines.append(f"  摘要: {summary}...")
        lines.append(f"  {link}\n")
    return "\n".join(lines)


async def _search_stackoverflow(
    query: str, limit: int, sort: str, config: AppConfig | None
) -> str:
    """Stack Overflow 搜索。"""
    s = sort if sort in ("relevance", "votes", "creation", "activity") else "relevance"
    url = "https://api.stackexchange.com/2.3/search"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        r = await client.get(url, params={"order": "desc", "sort": s, "intitle": query, "site": "stackoverflow", "pagesize": limit})
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        return "Stack Overflow: 无搜索结果"
    lines = [f"**Stack Overflow 搜索结果** ({len(items)} 条):\n"]
    for item in items:
        title = item.get("title", "")
        link = item.get("link", "")
        answers = item.get("answer_count", 0)
        views = item.get("view_count", 0)
        tags = item.get("tags", [])
        is_answered = item.get("is_answered", False)
        score = item.get("score", 0)
        status = "✅已解决" if is_answered else "❌未解决"
        lines.append(f"**{title}** [{status}] 👍{score}")
        lines.append(f"  回答: {answers} | 浏览: {views} | 标签: {', '.join(tags[:4])}")
        lines.append(f"  {link}\n")
    return "\n".join(lines)


async def _search_hackernews(
    query: str, limit: int, sort: str, config: AppConfig | None
) -> str:
    """Hacker News 搜索 (Algolia API)。"""
    endpoint = "search_by_date" if sort == "date" else "search"
    url = f"https://hn.algolia.com/api/v1/{endpoint}"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        r = await client.get(url, params={"query": query, "hitsPerPage": limit})
    r.raise_for_status()
    data = r.json()
    hits = data.get("hits", [])
    if not hits:
        return "Hacker News: 无搜索结果"
    lines = [f"**Hacker News 搜索结果** ({len(hits)} 条):\n"]
    for hit in hits:
        title = hit.get("title", "") or "(无标题)"
        url_val = hit.get("url", "")
        author = hit.get("author", "")
        points = hit.get("points", 0)
        comments = hit.get("num_comments", 0)
        created = hit.get("created_at", "")[:10]
        hn_link = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        link = url_val or hn_link
        lines.append(f"**{title}** 👍{points} 💬{comments}")
        lines.append(f"  作者: {author} | 日期: {created}")
        lines.append(f"  {link}\n")
    return "\n".join(lines)


async def _search_x(
    query: str, limit: int, config: AppConfig | None
) -> str:
    """X (Twitter) 搜索 — 网页抓取。"""
    # X/Twitter 搜索页面 (需要登录, 抓取可能不稳定)
    url = "https://x.com/search"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy, follow_redirects=True) as client:
        r = await client.get(
            url,
            params={"q": query, "src": "typed_query", "f": "live"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
    if r.status_code != 200:
        return f"X 搜索失败 (HTTP {r.status_code}),可能需要代理或登录"
    text = r.text
    # 尝试从 HTML 中提取推文内容 (X 是 SPA, 纯 HTML 抓取内容有限)
    # 提取 data-testid="tweetText" 内容
    tweets = re.findall(r'data-testid="tweetText"[^>]*>(.*?)</span>', text, re.DOTALL)
    if not tweets:
        # 备用: 尝试从 JSON 嵌入数据中提取
        tweets = re.findall(r'"full_text":"(.*?)"', text)
    if not tweets:
        return "X: 无法提取搜索结果(X 是单页应用,需要浏览器自动化才能有效抓取)"
    lines = [f"**X 搜索结果** ({min(len(tweets), limit)} 条):\n"]
    for i, tweet in enumerate(tweets[:limit]):
        # 清理 HTML 标签
        clean = re.sub(r"<[^>]+>", "", tweet).strip()
        if clean:
            lines.append(f"{i+1}. {clean}\n")
    return "\n".join(lines)


async def _search_weibo(
    query: str, limit: int, config: AppConfig | None
) -> str:
    """微博搜索 — 网页抓取。"""
    url = "https://s.weibo.com/weibo"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy, follow_redirects=True) as client:
        r = await client.get(
            url,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
    if r.status_code != 200:
        return f"微博搜索失败 (HTTP {r.status_code})"
    text = r.text
    # 提取微博内容
    cards = re.findall(r'<p node-type="feed_list_content"[^>]*>(.*?)</p>', text, re.DOTALL)
    # 提取用户名
    users = re.findall(r'class="name"[^>]*>(.*?)</a>', text)
    # 提取互动数据
    reposts = re.findall(r'<a[^>]*action-type="feed_list_forward"[^>]*>.*?(\d+)', text, re.DOTALL)
    comments = re.findall(r'<a[^>]*action-type="feed_list_comment"[^>]*>.*?(\d+)', text, re.DOTALL)
    likes = re.findall(r'<a[^>]*action-type="feed_list_like"[^>]*>.*?<em>(\d+)', text, re.DOTALL)
    if not cards:
        return "微博: 无法提取搜索结果(可能需要登录或页面结构已变更)"
    lines = [f"**微博搜索结果** ({min(len(cards), limit)} 条):\n"]
    for i in range(min(len(cards), limit)):
        # 清理 HTML
        content = re.sub(r"<[^>]+>", "", cards[i]).strip()
        user = re.sub(r"<[^>]+>", "", users[i]).strip() if i < len(users) else "未知"
        rp = reposts[i] if i < len(reposts) else "0"
        cm = comments[i] if i < len(comments) else "0"
        lk = likes[i] if i < len(likes) else "0"
        lines.append(f"**@{user}**")
        lines.append(f"  {content[:150]}")
        lines.append(f"  转发:{rp} 评论:{cm} 点赞:{lk}\n")
    return "\n".join(lines)


async def _search_zhihu(
    query: str, limit: int, config: AppConfig | None
) -> str:
    """知乎搜索 — 网页抓取。"""
    url = "https://www.zhihu.com/search"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy, follow_redirects=True) as client:
        r = await client.get(
            url,
            params={"type": "content", "q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
    if r.status_code != 200:
        return f"知乎搜索失败 (HTTP {r.status_code})"
    text = r.text
    # 知乎搜索结果在 JSON 数据中
    # 尝试提取初始数据
    match = re.search(r'<script id="js-initialData"[^>]*>(.*?)</script>', text, re.DOTALL)
    if match:
        import json
        try:
            data = json.loads(match.group(1))
            # 从 initialData 中提取搜索结果
            results = []
            search_data = data.get("initialState", {}).get("search", {})
            # 尝试多种路径
            for key in search_data:
                if isinstance(search_data[key], dict) and "items" in search_data[key]:
                    items = search_data[key]["items"]
                    for item in items:
                        obj = item.get("object", {}) if isinstance(item, dict) else {}
                        if obj.get("type") in ("answer", "article", "question"):
                            title = obj.get("title", "") or obj.get("question", {}).get("title", "")
                            excerpt = obj.get("excerpt", "") or obj.get("content", "")[:150]
                            link = obj.get("url", "")
                            if link and not link.startswith("http"):
                                link = f"https://www.zhihu.com{link}"
                            item_type = obj.get("type", "")
                            voteup = obj.get("voteup_count", 0)
                            results.append({"title": title, "excerpt": excerpt, "link": link, "type": item_type, "votes": voteup})
                            if len(results) >= limit:
                                break
                    if results:
                        break
            if results:
                lines = [f"**知乎搜索结果** ({len(results)} 条):\n"]
                for r_item in results:
                    type_label = {"answer": "回答", "article": "文章", "question": "问题"}.get(r_item["type"], r_item["type"])
                    lines.append(f"**[{type_label}] {r_item['title']}** 👍{r_item['votes']}")
                    lines.append(f"  {r_item['excerpt'][:120]}")
                    lines.append(f"  {r_item['link']}\n")
                return "\n".join(lines)
        except (json.JSONDecodeError, KeyError):
            pass
    # 降级: 正则提取
    titles = re.findall(r'<a[^>]*class="[^"]*SearchItem-Title[^"]*"[^>]*>(.*?)</a>', text, re.DOTALL)
    if not titles:
        return "知乎: 无法提取搜索结果(可能需要登录或页面结构已变更)"
    lines = [f"**知乎搜索结果** ({min(len(titles), limit)} 条):\n"]
    for i, title in enumerate(titles[:limit]):
        clean = re.sub(r"<[^>]+>", "", title).strip()
        lines.append(f"{i+1}. {clean}\n")
    return "\n".join(lines)


async def _search_douyin(
    query: str, limit: int, config: AppConfig | None
) -> str:
    """抖音搜索 — 网页抓取。"""
    url = "https://www.douyin.com/search/" + query
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy, follow_redirects=True) as client:
        r = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
    if r.status_code != 200:
        return f"抖音搜索失败 (HTTP {r.status_code})"
    text = r.text
    # 抖音是 SPA, 尝试从 SSR 数据中提取
    match = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', text, re.DOTALL)
    if match:
        import json
        from urllib.parse import unquote
        try:
            raw = unquote(match.group(1))
            data = json.loads(raw)
            # 递归搜索视频数据
            videos = _extract_douyin_videos(data)
            if videos:
                lines = [f"**抖音搜索结果** ({min(len(videos), limit)} 条):\n"]
                for v in videos[:limit]:
                    lines.append(f"**{v.get('title', '(无标题)')}**")
                    lines.append(f"  作者: {v.get('author', '未知')}")
                    lines.append(f"  点赞: {v.get('likes', 0)}")
                    lines.append(f"  {v.get('link', '')}\n")
                return "\n".join(lines)
        except (json.JSONDecodeError, KeyError):
            pass
    return "抖音: 无法提取搜索结果(抖音是单页应用,需要浏览器自动化才能有效抓取)"


def _extract_douyin_videos(data, depth=0) -> list[dict]:
    """递归从抖音 SSR 数据中提取视频信息。"""
    if depth > 10:
        return []
    results = []
    if isinstance(data, dict):
        # 检查是否是视频对象
        if "aweme" in data or "desc" in data:
            aweme = data.get("aweme", data)
            desc = aweme.get("desc", "")
            author = aweme.get("author", {}).get("nickname", "")
            stats = aweme.get("statistics", {})
            likes = stats.get("diggCount", 0)
            aweme_id = aweme.get("awemeId", "")
            link = f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""
            if desc:
                results.append({"title": desc[:80], "author": author, "likes": likes, "link": link})
        for v in data.values():
            results.extend(_extract_douyin_videos(v, depth + 1))
    elif isinstance(data, list):
        for item in data:
            results.extend(_extract_douyin_videos(item, depth + 1))
    return results


async def _search_bilibili(
    query: str, limit: int, search_type: str, config: AppConfig | None
) -> str:
    """B站搜索 (API)。"""
    st = search_type if search_type in ("video", "bangumi", "pgc", "live", "article") else "video"
    url = "https://api.bilibili.com/x/web-interface/search/type"
    proxy = _get_proxy(config)
    async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
        r = await client.get(
            url,
            params={"search_type": st, "keyword": query, "page": 1, "page_size": limit},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        return f"B站搜索失败: {data.get('message', '未知错误')}"
    results = data.get("data", {}).get("result", [])
    if not results:
        return "B站: 无搜索结果"
    lines = [f"**B站搜索结果** ({st}, {len(results)} 条):\n"]
    for item in results[:limit]:
        title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
        author = item.get("author", "") or item.get("uname", "")
        play = item.get("play", 0)
        danmaku = item.get("video_review", 0) or item.get("danmaku", 0)
        desc = (item.get("description", "") or "")[:80]
        bvid = item.get("bvid", "")
        link = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        lines.append(f"**{title}**")
        lines.append(f"  UP主: {author} | 播放: {play} | 弹幕: {danmaku}")
        if desc:
            lines.append(f"  简介: {desc}")
        lines.append(f"  {link}\n")
    return "\n".join(lines)


# ── 平台路由表 ──────────────────────────────────────────────


async def _search_with_timeout(searcher, *args, timeout: int = 15, **kwargs) -> str:
    """带超时的搜索包装。"""
    try:
        return await asyncio.wait_for(searcher(*args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        return f"搜索超时({timeout}秒),可能被网络限制,请检查代理设置(proxy_url)"
    except httpx.ConnectError:
        return "连接失败,无法访问该平台,可能被网络限制。请在 settings.json 中配置 proxy_url 代理"
    except httpx.ConnectTimeout:
        return f"连接超时({timeout}秒),可能被网络限制,请检查代理设置(proxy_url)"
    except httpx.HTTPStatusError as e:
        return f"搜索失败 (HTTP {e.response.status_code})"
    except Exception as e:
        return f"搜索失败: {e}"


_PLATFORM_SEARCHERS = {
    "github": _search_github,
    "arxiv": _search_arxiv,
    "stackoverflow": _search_stackoverflow,
    "hackernews": _search_hackernews,
    "x": _search_x,
    "weibo": _search_weibo,
    "zhihu": _search_zhihu,
    "douyin": _search_douyin,
    "bilibili": _search_bilibili,
}


def _parse_platforms(platform: str) -> list[str]:
    """解析平台参数,返回平台列表。"""
    platform = platform.strip().lower()
    if platform == "all":
        return list(_PLATFORM_SEARCHERS.keys())
    return [p.strip() for p in platform.split(",") if p.strip() in _PLATFORM_SEARCHERS]


# ── 主工具 ──────────────────────────────────────────────────


@tool
async def platform_search(
    query: str,
    platform: str = "all",
    limit: int = 10,
    sort: str = "",
    search_type: str = "",
    timeout: int = 15,
    config: AppConfig = None,
) -> str:
    """在指定平台搜索内容。支持 github/arxiv/stackoverflow/hackernews/x/weibo/zhihu/douyin/bilibili,或 all 搜索全部平台。platform 可用逗号分隔同时搜索多个平台,如 "github,arxiv"。

    Args:
        query: 搜索关键词
        platform: 搜索平台,多个用逗号分隔,或 "all" 搜索全部
        limit: 每个平台返回的结果数量(默认 10)
        sort: 排序方式(平台特有,如 github: stars/forks/updated,arxiv: relevance/lastUpdatedDate)
        search_type: 搜索类型(平台特有,如 github: repositories/code/issues,bilibili: video/bangumi)
        timeout: 单个平台搜索超时秒数(默认 15),超时返回错误信息
    """
    platforms = _parse_platforms(platform)
    if not platforms:
        return f"{TOOL_ERROR}: 未知平台 '{platform}'。支持的平台: {', '.join(_PLATFORM_SEARCHERS.keys())}, all"

    # 检查缓存
    ck = _cache_key(query, ",".join(platforms), limit=limit, sort=sort, search_type=search_type)
    cached = _search_cache.get(ck)
    if cached is not None:
        return cached

    # 并发搜索指定平台
    async def _run(p: str) -> str:
        searcher = _PLATFORM_SEARCHERS[p]
        kwargs = {"query": query, "limit": limit, "config": config}
        if p in ("github", "arxiv", "stackoverflow", "hackernews"):
            kwargs["sort"] = sort
        if p in ("github", "bilibili"):
            kwargs["search_type"] = search_type
        result = await _search_with_timeout(searcher, timeout=timeout, **kwargs)
        # 多平台时加平台标题分隔
        if len(platforms) > 1:
            result = f"\n{'='*20} {p.upper()} {'='*20}\n{result}"
        return result

    results = await asyncio.gather(*[_run(p) for p in platforms])
    combined = "\n".join(results)
    _search_cache[ck] = combined
    return combined


# ── 模块导出 ────────────────────────────────────────────────


def get_tools() -> list:
    """返回搜索工具列表。"""
    return [platform_search]


def get_all_tools() -> list:
    """返回全部搜索工具。"""
    return [platform_search]
