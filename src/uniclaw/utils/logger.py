import hashlib
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from uniclaw.context import get_app_dir

LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


def _log_dir_for(cwd: Path) -> str:
    """根据 cwd 计算日志目录路径。"""
    return str(get_app_dir(cwd) / "logs")


def get_logger(name: str, cwd: Path) -> logging.Logger:
    """获取指定名称和工作目录的 logger。

    每个 (name, cwd) 组合对应独立的 logger 和日志文件。
    """
    log_dir = _log_dir_for(cwd)
    # 用 cwd 的哈希区分不同项目的同名 logger
    cwd_hash = hashlib.md5(str(cwd).encode()).hexdigest()[:8]
    logger_name = f"{name}@{cwd_hash}"

    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    os.makedirs(log_dir, exist_ok=True)
    logger.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "uniclaw.agent.log"),
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

    return logger
