"""
Configuration management using Pydantic Settings
Loads from app.properties file and environment variables
"""

from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

from .utils.singleton import singleton


class Settings(BaseSettings):
    """Application settings with validation"""

    # Database Configuration
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL port")
    POSTGRES_DB: str = Field(
        default="scns_conductor", description="PostgreSQL database name"
    )
    POSTGRES_USER: str = Field(default="scns_user", description="PostgreSQL user")
    POSTGRES_PASSWORD: str = Field(default="", description="PostgreSQL password")

    # Redis Configuration
    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis password")

    # RQ Queue Configuration
    RQ_QUEUE_NAME: str = Field(default="scns_jobs", description="RQ queue name")
    RQ_RESULT_TTL: int = Field(default=86400, description="RQ result TTL in seconds")

    # API Server Configuration
    API_HOST: str = Field(default="0.0.0.0", description="API server host")
    API_PORT: int = Field(default=8000, description="API server port")
    API_WORKERS: int = Field(default=4, description="API server workers")

    # Worker Configuration
    WORKER_CONCURRENCY: int = Field(default=1, description="Worker concurrency")
    WORKER_BURST: bool = Field(default=False, description="Worker burst mode")

    # Resource Configuration
    NODE_NAME: str = Field(default="default-node", description="Node name")
    TOTAL_CPUS: int = Field(default=32, description="Total CPUs available")
    DEFAULT_PARTITION: str = Field(default="default", description="Default partition")

    # Logging Configuration
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FILE: Optional[str] = Field(default=None, description="Log file path")

    # Path Configuration
    JOB_WORK_BASE_DIR: str = Field(
        default="/var/scns-conductor/jobs",
        description="Base directory for job work directories",
    )
    SCRIPT_DIR: str = Field(
        default="/var/scns-conductor/scripts", description="Directory for job scripts"
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
            raise ValueError("TOTAL_CPUS must be at least 1")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v_upper

    def get_database_url(self, async_driver: bool = True) -> str:
        """
        Get database connection URL

        Args:
            async_driver: If True, use asyncpg driver; else use psycopg2

        Returns:
            Database URL string
        """
        driver = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
        return (
            f"{driver}://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_redis_url(self) -> str:
        """
        Get Redis connection URL

        Returns:
            Redis URL string
        """
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    def ensure_directories(self) -> None:
        """Ensure all required directories exist"""
        Path(self.JOB_WORK_BASE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.SCRIPT_DIR).mkdir(parents=True, exist_ok=True)

        if self.LOG_FILE:
            Path(self.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)


@singleton
class SettingsManager:
    """Singleton settings manager"""

    def __init__(self):
        self._settings: Optional[Settings] = None

    def get_settings(self) -> Settings:
        """Get or create settings instance"""
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    def reload_settings(self) -> Settings:
        """Reload settings from file"""
        self._settings = Settings()
        return self._settings


# Convenience function for getting settings
def get_settings() -> Settings:
    """Get application settings"""
    manager = SettingsManager()
    return manager.get_settings()
