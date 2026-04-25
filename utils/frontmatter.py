import re
import yaml
from typing import Any, Dict, Tuple


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    解析包含 frontmatter 的文本内容

    Frontmatter 是位于文件开头的 YAML 格式元数据，被 --- 标记包围。
    常见于 Markdown 文件中，用于存储标题、日期、标签等元信息。

    Args:
        content (str): 包含 frontmatter 的完整文本内容
                      格式示例：
                      ```
                      ---
                      title: 文章标题
                      date: 2024-01-01
                      tags:
                        - python
                        - tutorial
                      ---
                      这里是正文内容...
                      ```

    Returns:
        Tuple[Dict[str, Any], str]: 返回一个元组，包含：
            - 第一个元素：解析后的 frontmatter 字典（如果没有 frontmatter 则为空字典）
            - 第二个元素：去除 frontmatter 后的正文内容
    
    Examples:
        >>> content = "---\\ntitle: Hello\\n---\\nBody text"
        >>> metadata, body = parse_frontmatter(content)
        >>> metadata
        {'title': 'Hello'}
        >>> body
        'Body text'
    """
    if not content or not content.strip():
        return {}, content

    # 定义 frontmatter 的正则表达式模式
    # 匹配以 --- 开头和结尾的 YAML 块
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)"
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        # 如果没有找到 frontmatter，返回空字典和原文本
        return {}, content

    yaml_content = match.group(1)
    body_content = match.group(2)

    # 使用 PyYAML 安全地解析 YAML 内容
    try:
        metadata = yaml.safe_load(yaml_content)
        # safe_load 可能返回 None（当 YAML 为空时）
        if metadata is None:
            metadata = {}
    except yaml.YAMLError:
        # 如果 YAML 解析失败，返回空字典
        metadata = {}

    return metadata, body_content


def write_frontmatter(metadata: Dict[str, Any], body: str = "") -> str:
    """
    将元数据和正文内容组合成包含 frontmatter 的完整文本

    Args:
        metadata (Dict[str, Any]): 要写入的元数据字典
                                  支持字符串、数字、布尔值和简单列表类型
                                  示例：{'title': '文章标题', 'tags': ['python', 'tutorial']}
        body (str): 正文内容，默认为空字符串

    Returns:
        str: 包含 frontmatter 的完整文本内容
             格式为：
             ```
             ---
             key1: value1
             key2: value2
             ---
             正文内容
             ```

    Examples:
        >>> metadata = {'title': 'Hello', 'count': 42}
        >>> result = write_frontmatter(metadata, 'Body text')
        >>> print(result)
        ---
        title: Hello
        count: 42
        ---
        Body text
    """
    if not metadata:
        return body

    # 使用 PyYAML 将字典转换为 YAML 格式字符串
    yaml_content = yaml.dump(
        metadata,
        allow_unicode=True,  # 允许 Unicode 字符
        default_flow_style=False,  # 使用块样式而非流样式
        sort_keys=False  # 保持键的顺序
    ).rstrip()  # 移除末尾的换行符

    # 组合完整的 frontmatter 格式
    if body:
        return f"---\n{yaml_content}\n---\n{body}"
    else:
        return f"---\n{yaml_content}\n---\n"
