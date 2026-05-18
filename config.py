"""配置管理模块,用于从 .env 文件加载和管理环境变量。"""

from enum import StrEnum
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_env_path(env_filename: str = ".env") -> str:
    """
    获取 .env 文件的绝对路径。

    Args:
        env_filename: 环境文件名，默认为 .env

    Returns:
        .env 文件的绝对路径
    """
    return str(Path(__file__).parent / env_filename)


def load_env_file(env_path: Optional[str] = None) -> None:
    """
    从 .env 文件加载环境变量到当前环境中。

    Args:
        env_path: .env 文件的路径，如果为 None 则使用当前文件所在目录的 .env 文件
    """
    if env_path is None:
        env_path = get_env_path()

    load_dotenv(dotenv_path=env_path, override=True)


class Permissions(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    ACCEPT_ALL = "accept-all"
    PLAN = "plan"


class AppConfig(BaseSettings):
    """应用程序配置类，从环境变量中读取配置项。"""

    # API 配置（示例）
    OPENAI_API_KEY: Optional[str] = Field(default=None, description="API密钥")
    OPENAI_BASE_URL: Optional[str] = Field(default=None, description="API基础URL")
    model_name: Optional[str] = Field(
        default=None, description="主模型名称，用于处理复杂任务"
    )
    mini_model_name: Optional[str] = Field(
        default=None, description="迷你模型名称，用于处理简单快速的小任务"
    )
    temperature: Optional[float] = Field(default=0.7, description="模型温度")
    max_tokens: Optional[int] = Field(default=None, description="模型最大输出长度")
    top_p: Optional[float] = Field(default=None, description="模型概率")

    permission_mode: Permissions = Field(
        default=Permissions.AUTO, description="权限模式"
    )
    proxy_url: Optional[str] = Field(default=None, description="代理URL")

    cwd: Optional[str] = Field(default=None, description="工作目录")

    verbose: bool = Field(default=False, description="详细显示模式")

    depth: int = Field(default=0, description="任务深度")
    max_agent_depth: int = Field(default=3, description="最大agent深度")

    model_config = SettingsConfigDict(
        env_file=get_env_path(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs):
        """
        初始化配置，先加载 .env 文件再读取配置。

        如果 mini_model_name 未设置，则自动使用 model_name 的值。
        """
        load_env_file()
        super().__init__(**kwargs)

        # 如果 mini_model_name 未设置，则使用 model_name 的值
        if self.mini_model_name is None:
            self.mini_model_name = self.model_name


# 全局配置实例
config = AppConfig()


def get_config() -> AppConfig:
    """获取全局配置实例。"""
    return config


def get_config_dict(config: AppConfig) -> dict:
    """获取配置字典，所有值都已转换为 JSON 兼容格式。"""
    return config.model_dump(mode="json")
