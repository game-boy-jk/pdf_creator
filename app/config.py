from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen

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
    output_prefix: str = "generated/"
    pdf_font_object_key: str | None = None
    minio_secure: bool = False
    cache_ttl_sec: int = 300


@dataclass(frozen=True)
class ConfigServerSettings:
    url: str
    app_name: str
    profile: str
    label: str | None
    token: str | None
    timeout_sec: float
    fail_fast: bool


def get_settings() -> Settings:
    # Сначала пробуем конфиг-сервер, потом падаем на переменные окружения
    cfg = _load_config_server()

    return Settings(
        minio_endpoint=_require("MINIO_ENDPOINT", cfg),
        minio_public_endpoint=_require("MINIO_PUBLIC_ENDPOINT", cfg),
        minio_access_key=_require("MINIO_ACCESS_KEY", cfg),
        minio_secret_key=_require("MINIO_SECRET_KEY", cfg),
        minio_bucket=_require("MINIO_BUCKET", cfg),
        output_prefix=_prefix(_env("OUTPUT_PREFIX", cfg, "generated/")),
        pdf_font_object_key=_env("PDF_FONT_OBJECT_KEY", cfg, "") or None,
        minio_secure=_env("MINIO_SECURE", cfg, "false").lower() in {"1", "true", "yes"},
        cache_ttl_sec=int(_env("CACHE_TTL_SEC", cfg, "300")),
    )


def _env(name: str, cfg: dict, default: str) -> str:
    """Читает значение: сначала из env, потом из конфиг-сервера, потом default."""
    return os.getenv(name) or cfg.get(name) or default


def _require(name: str, cfg: dict) -> str:
    val = os.getenv(name) or cfg.get(name)
    if not val:
        raise RuntimeError(f"Missing required config: {name}")
    return str(val)


def _prefix(val: str) -> str:
    """Нормализует префикс: 'generated' и '/generated/' → 'generated/'"""
    stripped = val.strip().strip("/")
    # убирает пробелы (и другие пробельные символы) с начала и конца строки
    # убирает все слеши (/) с начала и конца уже очищенной строки.
    return f"{stripped}/" if stripped else ""


def _load_config_server() -> dict:
    url = os.getenv("CONFIG_SERVER_URL", "").strip()
    if not url:
        return {}

    settings = ConfigServerSettings(
        url=url.rstrip("/"),
        app_name=os.getenv("CONFIG_APP_NAME", "pdf-creator").strip(),
        profile=os.getenv("CONFIG_PROFILE", "default").strip(),
        label=os.getenv("CONFIG_LABEL") or None,
        token=os.getenv("CONFIG_SERVER_TOKEN") or None,
        timeout_sec=float(os.getenv("CONFIG_SERVER_TIMEOUT_SEC", "3")),
        fail_fast=os.getenv("CONFIG_FAIL_FAST", "false").lower() in {"1", "true", "yes"},
    )

    try:
        cfg = _fetch_config(settings)
        log.info("config_server_loaded url=%s app=%s profile=%s", settings.url, settings.app_name, settings.profile)
        return cfg
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if settings.fail_fast:
            raise RuntimeError("Cannot load configuration from config server") from exc
        log.warning("config_server_unavailable url=%s reason=%s — falling back to env", settings.url, exc)
        return {}


def _fetch_config(settings: ConfigServerSettings) -> dict:
    """Загружает конфиг из Spring Cloud Config Server и мержит propertySources."""
    parts = [settings.url, settings.app_name, settings.profile]
    if settings.label:
        parts.append(settings.label)
    url = "/".join(parts)

    headers = {"Accept": "application/json"}
    if settings.token:
        headers["Authorization"] = f"Bearer {settings.token}"

    with urlopen(Request(url, headers=headers), timeout=settings.timeout_sec) as resp:
        payload = json.loads(resp.read().decode())

    # Spring Cloud Config возвращает список propertySources от частного к общему.
    # reversed() чтобы более специфичные значения перезаписали общие.
    if "propertySources" not in payload:
        return payload

    merged: dict = {}
    for source in reversed(payload["propertySources"]):
        if isinstance(source.get("source"), dict):
            merged.update(source["source"])
    return merged