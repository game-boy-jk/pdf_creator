from __future__ import annotations

import json
import time
from io import BytesIO
from threading import RLock
from urllib.parse import quote

from minio import Minio
from minio.error import S3Error

from app.config import Settings


class StorageError(RuntimeError):
    pass


class FileStorage:
    def __init__(self, cfg: Settings) -> None:
        self.bucket = cfg.minio_bucket
        self.public_endpoint = cfg.minio_public_endpoint
        self.secure = cfg.minio_secure
        self.output_prefix = cfg.output_prefix
        self.font_key = cfg.pdf_font_object_key
        self.cache_ttl_sec = cfg.cache_ttl_sec
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._cache_lock = RLock()

        self.client = Minio(
            endpoint=cfg.minio_endpoint,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            secure=cfg.minio_secure,
            region="us-east-1",
        )

    def ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self.client.set_bucket_policy(self.bucket, self._public_read_policy())
        except S3Error as exc:
            raise StorageError(f"Cannot ensure MinIO bucket: {self.bucket}") from exc

    def read_bytes(self, key: str) -> bytes:
        cached = self._cached(key)
        if cached is not None:
            return cached

        try:
            res = self.client.get_object(self.bucket, key)
            try:
                payload = res.read()
                self._store_cache(key, payload)
                return payload
            finally:
                res.close()
                res.release_conn()
        except S3Error as exc:
            raise StorageError(f"Cannot read object from MinIO: {key}") from exc

    def write_bytes(self, key: str, payload: bytes) -> None:
        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=key,
                data=BytesIO(payload),
                length=len(payload),
                content_type="application/pdf",
            )
        except S3Error as exc:
            raise StorageError(f"Cannot write object to MinIO: {key}") from exc

    def read_font_bytes(self) -> bytes | None:
        if not self.font_key:
            return None
        return self.read_bytes(self.font_key)

    def url(self, key: str) -> str:
        endpoint = self.public_endpoint.rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            scheme = "https" if self.secure else "http"
            endpoint = f"{scheme}://{endpoint}"

        return f"{endpoint}/{quote(self.bucket)}/{quote(key)}"

    def _cached(self, key: str) -> bytes | None:
        if self.cache_ttl_sec <= 0:
            return None

        now = time.monotonic()
        with self._cache_lock:
            item = self._cache.get(key)
            if not item:
                return None
            expires_at, payload = item
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return payload

    def _store_cache(self, key: str, payload: bytes) -> None:
        if self.cache_ttl_sec <= 0:
            return

        with self._cache_lock:
            self._cache[key] = (time.monotonic() + self.cache_ttl_sec, payload)

    def _public_read_policy(self) -> str:
        resource = f"arn:aws:s3:::{self.bucket}/{self.output_prefix}*"
        return json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [resource],
                    }
                ],
            }
        )
