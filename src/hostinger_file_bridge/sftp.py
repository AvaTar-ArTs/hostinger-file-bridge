from __future__ import annotations

import hashlib
import io
import posixpath
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import paramiko

from .config import Settings
from .security import join_remote, safe_relative_path


class RemoteExistsError(FileExistsError):
    pass


class SFTPBridge:
    def __init__(self, settings: Settings):
        self.settings = settings

    @contextmanager
    def connect(self):
        client = paramiko.SSHClient()

        if self.settings.known_hosts_path and self.settings.known_hosts_path.exists():
            client.load_host_keys(str(self.settings.known_hosts_path))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        client.connect(
            hostname=self.settings.sftp_host,
            port=self.settings.sftp_port,
            username=self.settings.sftp_username,
            key_filename=str(self.settings.sftp_key_path),
            passphrase=self.settings.sftp_key_passphrase,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
            auth_timeout=20,
            banner_timeout=20,
        )
        try:
            sftp = client.open_sftp()
            try:
                yield client, sftp
            finally:
                sftp.close()
        finally:
            client.close()

    @staticmethod
    def _mkdir_p(sftp: paramiko.SFTPClient, remote_dir: str):
        parts = []
        cursor = posixpath.normpath(remote_dir)
        while cursor not in ("", "/"):
            parts.append(cursor)
            cursor = posixpath.dirname(cursor)
        for path in reversed(parts):
            try:
                sftp.stat(path)
            except FileNotFoundError:
                sftp.mkdir(path)

    def status(self) -> dict:
        with self.connect() as (_, sftp):
            attrs = sftp.stat(self.settings.remote_root)
            return {
                "ok": stat.S_ISDIR(attrs.st_mode),
                "host": self.settings.sftp_host,
                "port": self.settings.sftp_port,
                "username": self.settings.sftp_username,
                "remote_root": self.settings.remote_root,
                "host_key_verification": "known_hosts/system-only",
            }

    def list(self, relative_dir: str = "") -> list[dict]:
        path = self.settings.remote_root if not relative_dir else join_remote(
            self.settings.remote_root, relative_dir
        )
        with self.connect() as (_, sftp):
            entries = []
            for attr in sftp.listdir_attr(path):
                entries.append({
                    "name": attr.filename,
                    "size": attr.st_size,
                    "mtime": attr.st_mtime,
                    "is_dir": stat.S_ISDIR(attr.st_mode),
                })
            return sorted(entries, key=lambda x: (not x["is_dir"], x["name"].lower()))

    def mkdir(self, relative_dir: str) -> dict:
        remote = join_remote(self.settings.remote_root, relative_dir)
        with self.connect() as (_, sftp):
            self._mkdir_p(sftp, remote)
        return {"created": relative_dir}

    def exists(self, relative_path: str) -> bool:
        remote = join_remote(self.settings.remote_root, relative_path)
        with self.connect() as (_, sftp):
            try:
                sftp.stat(remote)
                return True
            except FileNotFoundError:
                return False

    def upload_stream(
        self,
        source: BinaryIO,
        relative_path: str,
        *,
        overwrite: bool = False,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> dict:
        rel = safe_relative_path(relative_path)
        remote = join_remote(self.settings.remote_root, rel)
        remote_dir = posixpath.dirname(remote)
        hasher = hashlib.sha256()
        written = 0

        with self.connect() as (_, sftp):
            self._mkdir_p(sftp, remote_dir)
            try:
                sftp.stat(remote)
                if not overwrite:
                    raise RemoteExistsError(
                        f"Remote path already exists: {rel}. Set overwrite=true explicitly."
                    )
            except FileNotFoundError:
                pass

            temp_remote = remote + ".uploading"
            try:
                with sftp.file(temp_remote, "wb") as dst:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        hasher.update(chunk)
                        dst.write(chunk)

                digest = hasher.hexdigest()
                if expected_size is not None and written != expected_size:
                    raise ValueError(
                        f"Size mismatch: uploaded {written} bytes, expected {expected_size}."
                    )
                if expected_sha256 and digest.lower() != expected_sha256.lower():
                    raise ValueError(
                        f"SHA-256 mismatch: got {digest}, expected {expected_sha256}."
                    )

                if overwrite:
                    try:
                        sftp.remove(remote)
                    except FileNotFoundError:
                        pass
                sftp.rename(temp_remote, remote)
                attrs = sftp.stat(remote)
                return {
                    "relative_path": rel,
                    "remote_path": remote,
                    "bytes": attrs.st_size,
                    "sha256": digest,
                    "verified_nonempty": attrs.st_size > 0,
                }
            except Exception:
                try:
                    sftp.remove(temp_remote)
                except Exception:
                    pass
                raise

    def upload_file(self, local_path: str | Path, relative_path: str, overwrite=False) -> dict:
        path = Path(local_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_size = path.stat().st_size
        hasher = hashlib.sha256()
        with path.open("rb") as digest_src:
            for chunk in iter(lambda: digest_src.read(1024 * 1024), b""):
                hasher.update(chunk)
        expected_sha = hasher.hexdigest()
        with path.open("rb") as src:
            return self.upload_stream(
                src,
                relative_path,
                overwrite=overwrite,
                expected_size=expected_size,
                expected_sha256=expected_sha,
            )

    def upload_bytes(self, data: bytes, relative_path: str, overwrite=False) -> dict:
        return self.upload_stream(
            io.BytesIO(data),
            relative_path,
            overwrite=overwrite,
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )

    def delete(self, relative_path: str) -> dict:
        remote = join_remote(self.settings.remote_root, relative_path)
        with self.connect() as (_, sftp):
            attrs = sftp.stat(remote)
            if stat.S_ISDIR(attrs.st_mode):
                raise IsADirectoryError(
                    "Directory deletion is intentionally disabled. Delete files individually."
                )
            sftp.remove(remote)
        return {"deleted": safe_relative_path(relative_path)}

    def extract_zip(self, relative_zip: str, relative_destination: str, overwrite=False) -> dict:
        zip_rel = safe_relative_path(relative_zip)
        dest_rel = safe_relative_path(relative_destination)
        remote_zip = join_remote(self.settings.remote_root, zip_rel)

        with tempfile.TemporaryDirectory(prefix="hfb-") as td:
            local_zip = Path(td) / "archive.zip"
            with self.connect() as (_, sftp):
                sftp.get(remote_zip, str(local_zip))

            extracted = []
            with zipfile.ZipFile(local_zip) as zf:
                for info in zf.infolist():
                    member = info.filename.replace("\\", "/")
                    if member.endswith("/"):
                        continue
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == stat.S_IFLNK:
                        raise ValueError(f"ZIP symlink rejected: {member}")

                    safe_member = safe_relative_path(member)
                    target_rel = posixpath.join(dest_rel, safe_member)
                    with zf.open(info, "r") as src:
                        result = self.upload_stream(
                            src,
                            target_rel,
                            overwrite=overwrite,
                            expected_size=info.file_size,
                        )
                    extracted.append(result)

            return {
                "source": zip_rel,
                "destination": dest_rel,
                "files_extracted": len(extracted),
                "files": extracted,
            }
