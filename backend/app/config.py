from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://market:market@localhost:5432/market_eagle")
    temporal_address: str = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    temporal_namespace: str = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue: str = os.getenv("TEMPORAL_TASK_QUEUE", "market-eagle")
    data_mode: str = os.getenv("MARKET_EAGLE_DATA_MODE", "live")
    iceberg_catalog_uri: str = os.getenv("ICEBERG_CATALOG_URI", "http://localhost:8181")
    s3_endpoint: str = os.getenv("S3_ENDPOINT", "http://localhost:4566")
    trino_host: str = os.getenv("TRINO_HOST", "localhost")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173")
    openrouter_timeout_seconds: float = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30"))


settings = Settings()
