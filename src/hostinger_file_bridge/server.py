from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from mcp.server.fastmcp import FastMCP

from .config import Settings
from .security import issue_upload_ticket, safe_relative_path, verify_upload_ticket
from .sftp import SFTPBridge

settings = Settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
log = logging.getLogger("hostinger-file-bridge")

bridge = SFTPBridge(settings)

mcp = FastMCP(
    "Hostinger File Bridge",
    instructions=(
        "Securely manage files beneath one configured Hostinger SFTP root. "
        "Never invent absolute remote paths; all tool paths are relative to the configured root."
    ),
    stateless_http=True,
    json_response=True,
)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": True,
    }
)
def remote_status() -> dict:
    """Use this when you need to verify Hostinger SFTP connectivity and the configured root."""
    return bridge.status()


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": True,
    }
)
def list_remote(relative_dir: str = "") -> dict:
    """Use this when you need to inspect files already stored under the configured Hostinger root."""
    return {"relative_dir": relative_dir, "entries": bridge.list(relative_dir)}


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": True,
    }
)
def mkdir_remote(relative_dir: str) -> dict:
    """Use this when you need to create a directory beneath the configured Hostinger root."""
    return bridge.mkdir(relative_dir)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
def upload_text(relative_path: str, content: str, overwrite: bool = False) -> dict:
    """Use this for small UTF-8 text/JSON/Markdown writes. Do not use it for large binary files."""
    return bridge.upload_bytes(content.encode("utf-8"), relative_path, overwrite=overwrite)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
def create_browser_upload(
    relative_path: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Use this when a large local file needs to be uploaded through the browser drop-zone.

    Returns a short-lived signed upload URL. The file bytes travel directly from the
    browser to this bridge, not through model/tool-call tokens.
    """
    if expected_size is not None and expected_size > settings.max_upload_bytes:
        raise ValueError("File exceeds configured upload maximum.")
    token = issue_upload_ticket(
        secret=settings.upload_signing_secret,
        relative_path=relative_path,
        ttl_seconds=settings.upload_ticket_ttl,
        overwrite=overwrite,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    base = settings.public_base_url.rstrip("/")
    return {
        "upload_url": f"{base}/drop/{token}",
        "expires_in_seconds": settings.upload_ticket_ttl,
        "relative_path": safe_relative_path(relative_path),
        "method": "POST multipart/form-data field name=file",
    }


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
def upload_from_url(
    source_url: str,
    relative_path: str,
    expected_sha256: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Use this when the source is a trusted, allowlisted HTTPS URL reachable by the bridge."""
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Only absolute HTTPS source URLs are allowed.")

    allowed_hosts = {
        item.strip().lower()
        for item in settings.source_url_hosts.split(",")
        if item.strip()
    }
    if not allowed_hosts:
        raise ValueError(
            "URL ingestion is disabled until HFB_SOURCE_URL_HOSTS is configured."
        )
    hostname = parsed.hostname.lower()
    if hostname not in allowed_hosts:
        raise ValueError(f"Source host is not allowlisted: {hostname}")

    for result in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM):
        addr = ipaddress.ip_address(result[4][0])
        if not addr.is_global:
            raise ValueError(f"Source host resolved to a non-public address: {addr}")

    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "HostingerFileBridge/0.1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        declared = resp.headers.get("Content-Length")
        if declared and int(declared) > settings.max_upload_bytes:
            raise ValueError("Remote file exceeds configured upload maximum.")

        with tempfile.NamedTemporaryFile(prefix="hfb-url-", delete=False) as tmp:
            temp_name = tmp.name
            total = 0
            hasher = hashlib.sha256()
            try:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise ValueError("Downloaded file exceeded configured upload maximum.")
                    hasher.update(chunk)
                    tmp.write(chunk)
            except Exception:
                Path(temp_name).unlink(missing_ok=True)
                raise

    try:
        digest = hasher.hexdigest()
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError(f"Source SHA-256 mismatch: got {digest}")
        return bridge.upload_file(temp_name, relative_path, overwrite=overwrite)
    finally:
        Path(temp_name).unlink(missing_ok=True)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
def delete_remote(relative_path: str) -> dict:
    """Use this only when the user explicitly asks to delete one remote file."""
    return bridge.delete(relative_path)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
        "idempotentHint": False,
    }
)
def extract_remote_zip(
    relative_zip: str,
    relative_destination: str,
    overwrite: bool = False,
) -> dict:
    """Use this when the user explicitly asks to extract a previously uploaded ZIP."""
    return bridge.extract_zip(relative_zip, relative_destination, overwrite=overwrite)


app = FastAPI(title="Hostinger File Bridge", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Hostinger File Bridge</title>
<style>
body{font-family:system-ui;background:#111827;color:#f9fafb;max-width:760px;margin:48px auto;padding:0 20px}
.card{background:#1f2937;border:1px solid #374151;border-radius:18px;padding:24px}
code{background:#0b1220;padding:2px 6px;border-radius:6px}
a{color:#93c5fd}
</style>
</head>
<body><div class="card">
<h1>Hostinger File Bridge</h1>
<p>Secure MCP + SFTP upload bridge.</p>
<p>MCP endpoint: <code>/mcp</code></p>
<p>Large uploads use a short-lived URL returned by <code>create_browser_upload</code>.</p>
</div></body></html>
"""


@app.get("/drop/{token}", response_class=HTMLResponse)
def drop_page(token: str):
    try:
        ticket = verify_upload_ticket(token, settings.upload_signing_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Upload to Hostinger</title>
<style>
body{{font-family:system-ui;background:#111827;color:#f9fafb;max-width:760px;margin:48px auto;padding:0 20px}}
.card{{background:#1f2937;border:1px solid #374151;border-radius:18px;padding:24px}}
input,button{{font-size:16px;margin:10px 0}}
button{{padding:10px 16px}}
pre{{white-space:pre-wrap;background:#0b1220;padding:16px;border-radius:12px}}
</style>
</head>
<body><div class="card">
<h1>Upload file</h1>
<p>Destination: <strong>{ticket.relative_path}</strong></p>
<form id="f">
<input type="file" name="file" required />
<br/><button type="submit">Upload & verify</button>
</form>
<pre id="out"></pre>
<script>
const f=document.getElementById('f'), out=document.getElementById('out');
f.addEventListener('submit', async (e)=>{{
 e.preventDefault();
 out.textContent='Uploading…';
 const body=new FormData(f);
 const r=await fetch(location.pathname, {{method:'POST', body}});
 const text=await r.text();
 out.textContent=text;
}});
</script>
</div></body></html>
"""


@app.post("/drop/{token}")
async def drop_upload(token: str, file: UploadFile = File(...)):
    try:
        ticket = verify_upload_ticket(token, settings.upload_signing_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    total = 0
    digest = hashlib.sha256()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="hfb-browser-", delete=False) as tmp:
            temp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Upload exceeds maximum size.")
                digest.update(chunk)
                tmp.write(chunk)

        if ticket.expected_size is not None and total != ticket.expected_size:
            raise HTTPException(
                status_code=400,
                detail=f"Size mismatch: got {total}, expected {ticket.expected_size}",
            )
        actual_sha = digest.hexdigest()
        if ticket.expected_sha256 and actual_sha.lower() != ticket.expected_sha256.lower():
            raise HTTPException(status_code=400, detail="SHA-256 mismatch.")

        result = bridge.upload_file(
            temp_path,
            ticket.relative_path,
            overwrite=ticket.overwrite,
        )
        return JSONResponse({"ok": True, "result": result})
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


app.mount("/mcp", mcp.streamable_http_app())


def main():
    import uvicorn

    uvicorn.run(
        "hostinger_file_bridge.server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
