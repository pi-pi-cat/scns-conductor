"""
使用 Pydantic Settings 进行配置管理
从 app.properties 文件和环境变量加载配置
"""

from functools import lru_cache
from typing import Optional
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger


class Settings(BaseSettings):
    """应用配置，包含参数校验"""

    # 数据库配置
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL 主机")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL 端口")
    POSTGRES_DB: str = Field(
        default="scns_conductor", description="PostgreSQL 数据库名称"
    )
    POSTGRES_USER: str = Field(default="scns_user", description="PostgreSQL 用户名")
    POSTGRES_PASSWORD: str = Field(default="", description="PostgreSQL 密码")

    # Redis 配置
    REDIS_HOST: str = Field(default="localhost", description="Redis 主机")
    REDIS_PORT: int = Field(default=6379, description="Redis 端口")
    REDIS_DB: int = Field(default=0, description="Redis 数据库编号")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis 密码")

    # RQ 队列配置
    RQ_QUEUE_NAME: str = Field(default="scns_jobs", description="RQ 队列名称")
    RQ_RESULT_TTL: int = Field(default=86400, description="RQ 结果存活时间（秒）")

    # API 服务器配置
    API_HOST: str = Field(default="0.0.0.0", description="API 服务器主机")
    API_PORT: int = Field(default=8000, description="API 服务器端口")
    API_WORKERS: int = Field(default=4, description="API 服务器进程数")

    # Worker 配置
    WORKER_CONCURRENCY: int = Field(default=1, description="Worker 并发数")
    WORKER_BURST: bool = Field(default=False, description="Worker 突发模式")

    # 资源配置
    NODE_NAME: str = Field(default="default-node", description="节点名称")
    TOTAL_CPUS: int = Field(default=32, description="可用 CPU 总数")
    DEFAULT_PARTITION: str = Field(default="default", description="默认分区名称")

    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_FILE: Optional[str] = Field(default=None, description="日志文件路径")

    # 路径配置
    JOB_WORK_BASE_DIR: str = Field(
        default="/var/scns-conductor/jobs",
        description="作业工作目录的根目录",
    )
    SCRIPT_DIR: str = Field(
        default="/var/scns-conductor/scripts", description="作业脚本存放目录"
    )

    model_config = SettingsConfigDict(
        env_file="app.properties",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("TOTAL_CPUS")
    @classmethod
    def validate_total_cpus(cls, v: int) -> int:
        if v < 1:
            raise ValueError("TOTAL_CPUS 至少为 1")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"LOG_LEVEL 必须为 {valid_levels} 中的一项")
        return v_upper

    def get_database_url(self, async_driver: bool = True) -> str:
        """
        获取数据库连接 URL

        参数:
            async_driver: 如果为 True，使用 asyncpg 驱动；否则使用 psycopg2

        返回:
            数据库连接 URL 字符串
        """
        driver = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
        return (
            f"{driver}://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_redis_url(self) -> str:
        """
        获取 Redis 连接 URL

        返回:
            Redis 连接 URL 字符串
        """
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    def ensure_directories(self) -> None:
        """确保所有需要的目录存在"""
        Path(self.JOB_WORK_BASE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.SCRIPT_DIR).mkdir(parents=True, exist_ok=True)

        if self.LOG_FILE:
            Path(self.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)


# ========== 配置获取函数 ==========
# 使用 functools.lru_cache 实现单例，更为 pythonic


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置实例（单例）

    使用 lru_cache 实现单例，比自定义单例装饰器更 pythonic

    返回:
        配置实例
    """
    settings = Settings()
    logger.info("Settings loaded")
    return settings


def reload_settings() -> Settings:
    """
    重新加载配置

    清除 lru_cache 缓存并重新加载配置

    返回:
        新的配置实例
    """
    get_settings.cache_clear()
    logger.info("Settings reloaded")
    return get_settings()
