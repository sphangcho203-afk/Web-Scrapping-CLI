from __future__ import annotations

import base64
import dataclasses
from pathlib import Path
from typing import Protocol

from .models import FetchResult
from .storage import DEFAULT_OBJECTS


class ObjectStore(Protocol):
    def put_capture(self, result: FetchResult) -> str | None: ...

    def get(self, location: str) -> bytes: ...


@dataclasses.dataclass(slots=True)
class LocalObjectStore:
    root: Path = DEFAULT_OBJECTS

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_capture(self, result: FetchResult) -> str | None:
        payload = capture_bytes(result)
        if payload is None:
            return None
        target = self.root / result.sha256[:2] / result.sha256
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
        return str(target)

    def get(self, location: str) -> bytes:
        return Path(location).read_bytes()


@dataclasses.dataclass(slots=True)
class S3ObjectStore:
    bucket: str
    prefix: str = "internet-hands/objects"
    endpoint_url: str | None = None
    region_name: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None

    def __post_init__(self) -> None:
        if not self.bucket.strip():
            raise ValueError("S3 bucket cannot be empty")
        self.prefix = self.prefix.strip("/")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install internet-hands[s3] to use S3 object storage") from exc

        kwargs: dict[str, object] = {}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.region_name:
            kwargs["region_name"] = self.region_name
        if self.access_key_id:
            kwargs["aws_access_key_id"] = self.access_key_id
        if self.secret_access_key:
            kwargs["aws_secret_access_key"] = self.secret_access_key
        if self.session_token:
            kwargs["aws_session_token"] = self.session_token
        self._client = boto3.client("s3", **kwargs)

    def put_capture(self, result: FetchResult) -> str | None:
        payload = capture_bytes(result)
        if payload is None:
            return None
        key = self._key(result.sha256)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception:  # noqa: BLE001 -- compatible stores vary in not-found exception type
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType=result.content_type or "application/octet-stream",
                Metadata={"sha256": result.sha256},
            )
        return f"s3://{self.bucket}/{key}"

    def get(self, location: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not location.startswith(prefix):
            raise ValueError("Object location does not belong to configured S3 bucket")
        key = location[len(prefix) :]
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def _key(self, sha256: str) -> str:
        parts = [part for part in (self.prefix, sha256[:2], sha256) if part]
        return "/".join(parts)


def capture_bytes(result: FetchResult) -> bytes | None:
    if result.body_base64 is not None:
        return base64.b64decode(result.body_base64)
    if result.body_text is not None:
        return result.body_text.encode("utf-8")
    return None
