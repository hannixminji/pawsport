import os
from enum import StrEnum

from argon2 import PasswordHasher
from argon2.low_level import Type
from pydantic import RedisDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    APP_NAME: str = "PawsPort"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = None
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class CryptSettings(BaseSettings):
    SECRET_KEY: SecretStr = SecretStr("secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


class Argon2Settings(BaseSettings):
    TIME_COST: int = int(os.getenv("ARGON2_TIME_COST", 4))
    MEMORY_COST: int = int(os.getenv("ARGON2_MEMORY_COST", 131072))
    PARALLELISM: int = int(os.getenv("ARGON2_PARALLELISM", 4))
    HASH_LEN: int = int(os.getenv("ARGON2_HASH_LEN", 32))
    SALT_LEN: int = int(os.getenv("ARGON2_SALT_LEN", 16))
    ENCODING: str = os.getenv("ARGON2_ENCODING", "utf-8")
    TYPE: Type = Type.ID

    @computed_field
    @property
    def password_hasher(self) -> PasswordHasher:
        return PasswordHasher(
            time_cost=self.TIME_COST,
            memory_cost=self.MEMORY_COST,
            parallelism=self.PARALLELISM,
            hash_len=self.HASH_LEN,
            salt_len=self.SALT_LEN,
            encoding=self.ENCODING,
            type=self.TYPE,
        )


class DatabaseSettings(BaseSettings):
    pass


class SQLiteSettings(DatabaseSettings):
    SQLITE_URI: str = "./sql_app.db"
    SQLITE_SYNC_PREFIX: str = "sqlite:///"
    SQLITE_ASYNC_PREFIX: str = "sqlite+aiosqlite:///"


class MySQLSettings(DatabaseSettings):
    MYSQL_USER: str = "username"
    MYSQL_PASSWORD: str = "password"
    MYSQL_SERVER: str = "localhost"
    MYSQL_PORT: int = 5432
    MYSQL_DB: str = "dbname"
    MYSQL_SYNC_PREFIX: str = "mysql://"
    MYSQL_ASYNC_PREFIX: str = "mysql+aiomysql://"
    MYSQL_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MYSQL_URI(self) -> str:
        credentials = f"{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
        location = f"{self.MYSQL_SERVER}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        return f"{credentials}@{location}"


class PostgresSettings(DatabaseSettings):
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URI(self) -> str:
        if self.POSTGRES_URL:
            uri = self.POSTGRES_URL
            if "://" in uri:
                uri = uri.split("://", 1)[1]
            return uri

        credentials = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
        location = f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return f"{credentials}@{location}"


class FirstUserSettings(BaseSettings):
    ADMIN_NAME: str = "admin"
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: SecretStr = SecretStr("!Ch4ng3Th1sP4ssW0rd!")


class TestSettings(BaseSettings):
    ...


class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    REDIS_CACHE_URL: str | None = None

    @model_validator(mode="after")
    def set_cache_url(self) -> "RedisCacheSettings":
        if self.REDIS_CACHE_URL is None:
            object.__setattr__(
                self,
                "REDIS_CACHE_URL",
                str(RedisDsn(f"redis://{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}")),
            )
        return self


class RedisAdminSessionSettings(BaseSettings):
    REDIS_ADMIN_SESSION_HOST: str = "localhost"
    REDIS_ADMIN_SESSION_PORT: int = 6379
    REDIS_ADMIN_SESSION_DB: int = 1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_ADMIN_SESSION_URL(self) -> str:
        return f"redis://{self.REDIS_ADMIN_SESSION_HOST}:{self.REDIS_ADMIN_SESSION_PORT}/{self.REDIS_ADMIN_SESSION_DB}"


class ClientSideCacheSettings(BaseSettings):
    CLIENT_CACHE_MAX_AGE: int = 60


class RedisQueueSettings(BaseSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379


class RedisRateLimiterSettings(BaseSettings):
    REDIS_RATE_LIMIT_HOST: str = "localhost"
    REDIS_RATE_LIMIT_PORT: int = 6379

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_RATE_LIMIT_URL(self) -> str:
        return f"redis://{self.REDIS_RATE_LIMIT_HOST}:{self.REDIS_RATE_LIMIT_PORT}"


class DefaultRateLimitSettings(BaseSettings):
    DEFAULT_RATE_LIMIT_LIMIT: int = 10
    DEFAULT_RATE_LIMIT_PERIOD: int = 3600

    DEFAULT_GUEST_RATE_LIMIT_LIMIT: int = 5
    DEFAULT_GUEST_RATE_LIMIT_PERIOD: int = 3600


class AdminSessionSettings(BaseSettings):
    ADMIN_SESSION_TTL_SECONDS: int = 1800
    ADMIN_SESSION_ABSOLUTE_TTL_SECONDS: int = 604800
    ADMIN_SESSION_SIGNING_SECRET: SecretStr

    ADMIN_SESSION_COOKIE_SECURE: bool = True
    ADMIN_SESSION_COOKIE_SAMESITE: str = "lax"
    ADMIN_SESSION_COOKIE_PATH: str = "/api/v1/admin"

    ADMIN_SESSION_MAXIMUM_SESSIONS_PER_USER: int = 3


class AdminAuthSettings(BaseSettings):
    LOGIN_WINDOW_SECONDS: int = 60
    LOGIN_MAX_ATTEMPTS_PER_IP_USERNAME: int = 10
    LOGIN_MAX_ATTEMPTS_PER_IP: int = 10


class EnvironmentOption(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = ["*"]
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]


class GCSSettings(BaseSettings):
    GCS_BUCKET_NAME: str = "pawsport"
    GCS_SIGNED_URL_VERSION: str = "v4"
    GCS_VIEW_SIGNED_URL_EXPIRATION_MINUTES: int = 60
    GCS_DOWNLOAD_SIGNED_URL_EXPIRATION_MINUTES: int = 60
    GCS_UPLOAD_SIGNED_URL_EXPIRATION_MINUTES: int = 60
    GCS_RESUMABLE_UPLOAD_SIGNED_URL_EXPIRATION_MINUTES: int = 60
    GOOGLE_APPLICATION_CREDENTIALS_JSON: SecretStr | None = None


class QdrantCloudSettings(BaseSettings):
    QDRANT_CLOUD_URL: str = "http://localhost:6333"
    QDRANT_CLOUD_API_KEY: SecretStr = SecretStr("")


class NotificationSettings(BaseSettings):
    NEARBY_ALERT_CENTER_RADIUS_METERS: int = 3_000


class MLServiceSettings(BaseSettings):
    ML_BASE_URL: str = "http://ml:9000"


class PetSettings(BaseSettings):
    QR_BASE_URL: str = "http://localhost:8000/api/v1/pets/qr"


class Settings(
    AppSettings,
    SQLiteSettings,
    PostgresSettings,
    CryptSettings,
    Argon2Settings,
    FirstUserSettings,
    TestSettings,
    RedisCacheSettings,
    RedisAdminSessionSettings,
    ClientSideCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    DefaultRateLimitSettings,
    AdminSessionSettings,
    AdminAuthSettings,
    EnvironmentSettings,
    CORSSettings,
    GCSSettings,
    QdrantCloudSettings,
    NotificationSettings,
    MLServiceSettings,
    PetSettings,
):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
