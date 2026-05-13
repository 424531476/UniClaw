import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FORMAT = "[%(asctime)s] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


def get_logger(name: str = "agent") -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 文件处理器 - 使用RotatingFileHandler避免文件锁定问题
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "agent.log"),
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 确保logger不会传播到根logger（避免重复输出）
    logger.propagate = False

    return logger