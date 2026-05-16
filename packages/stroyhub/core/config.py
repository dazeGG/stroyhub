from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "local"
    log_level: str = "INFO"
    timezone: str = "Asia/Yakutsk"
    database_url: str = "postgresql+psycopg://stroyhub:stroyhub@localhost:5432/stroyhub"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="STROYHUB_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
