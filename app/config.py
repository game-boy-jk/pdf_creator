from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


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
    cfg = _load_config_server()

    return Settings(
        minio_endpoint=_get("MINIO_ENDPOINT", cfg, required=True),
        minio_public_endpoint=_get("MINIO_PUBLIC_ENDPOINT", cfg, required=True),
        minio_access_key=_get("MINIO_ACCESS_KEY", cfg, required=True),
        minio_secret_key=_get("MINIO_SECRET_KEY", cfg, required=True),
        minio_bucket=_get("MINIO_BUCKET", cfg, required=True),
        output_prefix=_normalize_prefix(_get("OUTPUT_PREFIX", cfg, default="generated/")),
        pdf_font_object_key=_optional(_get("PDF_FONT_OBJECT_KEY", cfg, default="")),
        minio_secure=_to_bool(_get("MINIO_SECURE", cfg, default="false")),
        cache_ttl_sec=int(_get("CACHE_TTL_SEC", cfg, default="300")),
    )


def _get(
    name: str,
    cfg: dict[str, Any],
    *,
    required: bool = False,
    default: str | None = None,
) -> str:
    val = os.getenv(name)
    if val is None:
        val = cfg.get(name)
    if val is None:
        val = default
    if required and not val:
        raise RuntimeError(f"Missing required config: {name}")
    return str(val)


def _load_config_server() -> dict[str, Any]:
    client = _config_server_settings()
    if client is None:
        return {}

    try:
        payload = _request_config(client)
        return _parse_config_payload(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if client.fail_fast:
            raise RuntimeError("Cannot load configuration from config server") from exc
        return {}


def _config_server_settings() -> ConfigServerSettings | None:
    url = os.getenv("CONFIG_SERVER_URL", "").strip()
    if not url:
        return None

    return ConfigServerSettings(
        url=url.rstrip("/"),
        app_name=os.getenv("CONFIG_APP_NAME", "pdf-creator").strip(),
        profile=os.getenv("CONFIG_PROFILE", "default").strip(),
        label=_optional(os.getenv("CONFIG_LABEL", "")),
        token=_optional(os.getenv("CONFIG_SERVER_TOKEN", "")),
        timeout_sec=float(os.getenv("CONFIG_SERVER_TIMEOUT_SEC", "3")),
        fail_fast=_to_bool(os.getenv("CONFIG_FAIL_FAST", "false")),
    )


def _request_config(client: ConfigServerSettings) -> dict[str, Any]:
    url = _config_url(client)
    headers = {"Accept": "application/json"}
    if client.token:
        headers["Authorization"] = f"Bearer {client.token}"

    req = Request(url, headers=headers)
    with urlopen(req, timeout=client.timeout_sec) as res:
        payload = res.read().decode("utf-8")
    return json.loads(payload)


def _config_url(client: ConfigServerSettings) -> str:
    base = f"{client.url}/{client.app_name}/{client.profile}"
    if client.label:
        return f"{base}/{client.label}"
    return base


def _parse_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "propertySources" not in payload:
        return payload

    merged: dict[str, Any] = {}
    for item in reversed(payload.get("propertySources", [])):
        source = item.get("source", {})
        if isinstance(source, dict):
            merged.update(source)

    return merged


def _to_bool(val: str) -> bool:
    return val.lower() in {"1", "true", "yes", "y", "on"}


def _optional(val: str) -> str | None:
    value = val.strip()
    return value or None


def _normalize_prefix(val: str) -> str:
    prefix = val.strip().strip("/")
    return f"{prefix}/" if prefix else ""
