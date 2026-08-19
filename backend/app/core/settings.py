"""Application configuration loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the application.

    The default database URL intentionally uses the postgres superuser for local
    development to ensure migrations can run. Production deployments should use
    a dedicated app_user with appropriate RLS grants.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rfp_response"
    migrations_database_url: str | None = None
    redis_url: str | None = None
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    log_level: str = "INFO"

    # OIDC Configuration
    oidc_issuer: str = "http://localhost:8081/realms/rfp-response-intelligence"
    oidc_client_id: str = "rfp-response-intelligence-web"
    oidc_client_secret: str = "local-development-only"
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"

    # JWT Configuration
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # Frontend URL for invite links
    frontend_url: str = "http://localhost:5173"
    # CORS allowed frontend origins (comma-separated string)
    frontend_urls_str: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def frontend_urls(self) -> list[str]:
        return [url.strip() for url in self.frontend_urls_str.split(",")]

    # LLM Provider Configuration
    llm_provider: str = "mock"
    llm_api_key: str = "not-used-in-local-development"
    llm_default_model_fast: str = "gpt-4o-mini"
    llm_default_model_reasoning: str = "gpt-4o"
    llm_default_model_vision: str = "gpt-4o"
    llm_cache_ttl_seconds: int = 86400


settings = Settings()
