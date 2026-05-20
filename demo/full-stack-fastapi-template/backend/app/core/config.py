import warnings
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


def expand_cors_origin_aliases(origins: list[str]) -> list[str]:
    aliases_by_origin = {
        "https://enderai.xyz": "https://www.enderai.xyz",
        "https://www.enderai.xyz": "https://enderai.xyz",
    }
    expanded: list[str] = []
    for origin in origins:
        normalized_origin = origin.rstrip("/")
        expanded.append(normalized_origin)

        parsed_origin = urlsplit(normalized_origin)
        if parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
            continue

        alias = aliases_by_origin.get(normalized_origin)
        if alias:
            expanded.append(alias)

    return list(dict.fromkeys(expanded))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # IMPORTANT:
    # This MUST be set explicitly in deployments. If it is generated per-process,
    # JWTs issued by one worker won't validate on another worker (e.g. multi-worker setup).
    # Keep the default as a sentinel and enforce it via _check_default_secret().
    SECRET_KEY: str = "changethis"
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    AGENT_CREDENTIAL_EXPIRE_DAYS: int = 365
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        configured_origins = [
            str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS
        ] + [self.FRONTEND_HOST.rstrip("/")]
        return expand_cors_origin_aliases(configured_origins)

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_PRICE_ID: str | None = None
    STRIPE_PRICE_ID_PRO: str | None = None
    STRIPE_PRICE_ID_MAX: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_API_BASE_URL: str = "https://api.stripe.com"
    FIREBASE_PROJECT_ID: str | None = None
    FIREBASE_SERVICE_ACCOUNT_JSON: str | None = None
    # Taskforce Search — managed inference + BYOK + embeddings.
    # All optional so dev environments without keys can still boot; Search
    # endpoints surface a clear error when a required key is missing.
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    # url-safe base64-encoded 32-byte key (cryptography.fernet.Fernet.generate_key()).
    # Required when BYOK is enabled in prod; if unset, BYOK endpoints refuse writes.
    BYOK_ENCRYPTION_KEY: str | None = None
    SEARCH_EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEARCH_ANSWER_MODEL: str = "claude-sonnet-4-6"
    # Cron-sweep cadence for the embedding indexer (seconds between sweeps).
    SEARCH_INDEX_SWEEP_INTERVAL_SECONDS: int = 30
    SEARCH_INDEX_BATCH_SIZE: int = 50

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
