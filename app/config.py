import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    minio_endpoint: str
    minio_public_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    pdf_font_object_key: str
    output_prefix: str = "generated/"
    minio_secure: bool = False
    cache_ttl_sec: int = 300


def get_settings() -> Settings:
    return Settings(
        minio_endpoint=_env("MINIO_ENDPOINT"),
        minio_public_endpoint=_env("MINIO_PUBLIC_ENDPOINT"),
        minio_access_key=_env("MINIO_ACCESS_KEY"),
        minio_secret_key=_env("MINIO_SECRET_KEY"),
        minio_bucket=_env("MINIO_BUCKET"),
        output_prefix=_prefix(_env("OUTPUT_PREFIX", "generated/")),
        minio_secure=_bool(_env("MINIO_SECURE", "false")),
        cache_ttl_sec=int(_env("CACHE_TTL_SEC", "300")),
        pdf_font_object_key=_env("PDF_FONT_OBJECT_KEY")
    )


def _env(name: str, default: str | None = None) -> str:
    """Без default — обязательный параметр. С default — опциональный."""
    val = os.getenv(name) or default
    if val is None:
        raise RuntimeError(f"Missing required config: {name}")
    return str(val)


def _bool(val: str) -> bool:
    return val.strip().lower() in {"1", "true", "yes"}


def _prefix(val: str) -> str:
    stripped = val.strip().strip("/")
    return f"{stripped}/" if stripped else ""