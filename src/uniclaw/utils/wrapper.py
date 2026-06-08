import time
import traceback
from pathlib import Path


def error_catch(name: str):
    """返回一个异常捕获装饰器。

    该装饰器将包装目标函数,在函数执行过程中捕获任何异常,
    并将异常信息连同完整堆栈追踪写入指定 logger。
    捕获后会重新抛出异常,保证调用方仍能看到原始错误。

    Args:
        name: logger 名称,会从函数 kwargs 中的 task.session.root_dir 获取日志目录。

    Returns:
        wrapper: 用于装饰目标函数的包装器。
    """

    def wrapper(fun):
        def inner(*args, **kwargs):
            try:
                ret = fun(*args, **kwargs)
                return ret
            except Exception as e:
                from uniclaw.utils.logger import get_logger

                task = kwargs.get("task")
                if not task:
                    raise RuntimeError(f"error_catch({name}): 缺少 task 参数,无法获取 session.root_dir")
                logger = get_logger(name, task.session.root_dir)

                err = str(e)
                if err == "":
                    err = str(type(e))
                detailed = f"{fun.__name__}\n{traceback.format_exc()}"
                msg = f"{err}\n\n{detailed}"
                logger.error(msg)
                raise e

        if hasattr(fun, "__name__"):
            inner.__name__ = fun.__name__
        return inner

    return wrapper
