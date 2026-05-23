import time
import functools
from typing import Any, Callable


def ttl_cache(ttl_seconds: float = 60):
    """带过期时间的缓存装饰器,ttl_seconds 秒内重复调用返回缓存结果。"""

    def decorator(func: Callable) -> Callable:
        cache: dict[str, Any] = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.monotonic()
            key = (func.__qualname__, args, tuple(sorted(kwargs.items())))
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < ttl_seconds:
                    return result
            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator
