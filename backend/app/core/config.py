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
    # T03：导入任务原始文件的临时存放目录；确认、取消或失败后清理。
    import_task_storage_dir: str = ".runtime/import-tasks"
    # T10：可选的语言模型问答服务（OpenAI 兼容）。留空时使用结构化本地回答。
    llm_provider: str | None = None
    llm_model: str = "qwen2.5:7b-instruct"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_timeout: float = 60
    # T01：鉴权开关与账号策略。默认关闭，使本地开发与既有 1.0 流程保持匿名管理员；
    # 生产部署与联合验收前必须显式开启，否则业务接口不校验登录。
    auth_required: bool = False
    session_ttl_minutes: int = 720
    password_hash_iterations: int | None = None

    @field_validator("import_model_url")
    @classmethod
    def local_import_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("智能导入仅允许本机 HTTP Ollama 地址")
        return value

    @field_validator("session_ttl_minutes")
    @classmethod
    def session_ttl_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("会话有效期必须为正整数分钟")
        return value

    @field_validator("password_hash_iterations")
    @classmethod
    def iterations_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1000:
            raise ValueError("口令迭代次数不得低于 1000")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
