from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "循影定检 API"
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./xunying.db"
    backend_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    recommendation_artifact_path: str | None = None
    import_model_url: str = "http://127.0.0.1:11434"
    import_model: str = "qwen3-vl:4b-instruct"
    import_model_timeout: float = 240

    @field_validator("import_model_url")
    @classmethod
    def local_import_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("智能导入仅允许本机 HTTP Ollama 地址")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
