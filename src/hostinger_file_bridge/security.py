from __future__ import annotations

import base64
import hashlib
import hmac
import json
import posixpath
import time
from dataclasses import dataclass


class PathViolation(ValueError):
    pass


def safe_relative_path(value: str) -> str:
    """Return a normalized safe relative POSIX path.

    Rejects absolute paths, traversal, empty names, NULs, and home expansion.
    """
    value = (value or "").strip().replace("\\", "/")
    if not value:
        raise PathViolation("A non-empty relative path is required.")
    if "\x00" in value:
        raise PathViolation("NUL bytes are not allowed.")
    if value.startswith(("/", "~")):
        raise PathViolation("Absolute/home paths are not allowed.")
    normalized = posixpath.normpath(value)
    if normalized in {".", ".."} or normalized.startswith("../"):
        raise PathViolation("Path traversal is not allowed.")
    return normalized.lstrip("/")


def join_remote(root: str, relative: str) -> str:
    rel = safe_relative_path(relative)
    root_norm = posixpath.normpath(root)
    joined = posixpath.normpath(posixpath.join(root_norm, rel))
    prefix = root_norm.rstrip("/") + "/"
    if not joined.startswith(prefix):
        raise PathViolation("Resolved path escaped the configured remote root.")
    return joined


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class UploadTicket:
    relative_path: str
    overwrite: bool
    expected_size: int | None
    expected_sha256: str | None
    exp: int


def issue_upload_ticket(
    *,
    secret: str,
    relative_path: str,
    ttl_seconds: int,
    overwrite: bool = False,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> str:
    rel = safe_relative_path(relative_path)
    payload = {
        "v": 1,
        "path": rel,
        "overwrite": bool(overwrite),
        "size": expected_size,
        "sha256": expected_sha256.lower() if expected_sha256 else None,
        "exp": int(time.time()) + int(ttl_seconds),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_upload_ticket(token: str, secret: str) -> UploadTicket:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed upload ticket.") from exc

    expected = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid upload ticket signature.")

    payload = json.loads(_b64url_decode(body))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Upload ticket expired.")

    return UploadTicket(
        relative_path=safe_relative_path(payload["path"]),
        overwrite=bool(payload.get("overwrite", False)),
        expected_size=payload.get("size"),
        expected_sha256=payload.get("sha256"),
        exp=int(payload["exp"]),
    )
