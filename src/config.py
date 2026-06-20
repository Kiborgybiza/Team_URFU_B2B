from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NeoMarket B2B Service"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "neomarket_b2b"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_echo: bool = False

    jwt_secret_key: str = "dev-secret"
    jwt_algorithm: str = "HS256"

    moderation_url: str = "http://moderation:8000"
    b2b_to_mod_key: str = "dev-b2b-to-moderation-key"
    moderation_to_b2b_key: str = "dev-moderation-to-b2b-key"
    moderation_timeout_seconds: float = 3.0

    b2c_url: str = "http://b2c:8000"
    b2b_to_b2c_key: str = "dev-b2b-to-b2c-key"
    b2c_to_b2b_key: str = "dev-b2c-to-b2b-key"
    b2c_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
