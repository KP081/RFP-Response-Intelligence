"""Application configuration loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the application.

    The default database URL intentionally uses a dedicated app_user role so RLS
    is enforced in local development unless a deployment-specific `.env` overrides it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://app_user:app_password@localhost:5432/rfp_response"
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

    # JWT Configuration
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30


settings = Settings()
