from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    postgres_user: str = Field(default="agent_user", alias="POSTGRES_USER")
    postgres_password: str = Field(default="replace_with_local_password", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="agent_db", alias="POSTGRES_DB")
    database_url: str = Field(default="postgresql+asyncpg://agent_user:replace_with_local_password@db:5432/agent_db", alias="DATABASE_URL")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_model: Optional[str] = Field(default=None, alias="LLM_MODEL")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="/app/logs/agent_activity.log", alias="LOG_FILE")

    task_max_retries: int = Field(default=3, alias="TASK_MAX_RETRIES")
    task_retry_backoff_seconds: int = Field(default=2, alias="TASK_RETRY_BACKOFF_SECONDS")
    task_timeout_seconds: int = Field(default=300, alias="TASK_TIMEOUT_SECONDS")

    websocket_heartbeat_seconds: int = Field(default=20, alias="WEBSOCKET_HEARTBEAT_SECONDS")
    workspace_ttl_seconds: int = Field(default=86400, alias="WORKSPACE_TTL_SECONDS")

    checkpoint_mode: str = Field(default="auto", alias="CHECKPOINT_MODE")

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="allow",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v):
        if not (v.startswith("postgresql") or v.startswith("sqlite")):
            raise ValueError("DATABASE_URL must use postgresql or sqlite")
        return v

    @field_validator("checkpoint_mode")
    @classmethod
    def validate_checkpoint_mode(cls, v):
        allowed = {"auto", "postgres", "memory"}
        if v.lower() not in allowed:
            raise ValueError(f"CHECKPOINT_MODE must be one of {allowed}, got '{v}'")
        return v


settings = Settings()
