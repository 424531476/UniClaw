"""中英文分词工具。"""

import re

import jieba


def tokenize(text: str) -> list[str]:
    """中英文分词:中文用 jieba,英文按单词。

    >>> tokenize("Python 代码风格")
    ['python', '代码', '风格']
    """
    en_words = re.findall(r"[a-zA-Z_]+", text.lower())
    cn_tokens = [w for w in jieba.cut(text.lower()) if re.match(r"[一-鿿]", w)]
    return en_words + cn_tokens
