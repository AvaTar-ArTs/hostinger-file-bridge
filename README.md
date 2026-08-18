# Hostinger File Bridge

A secure file-transfer bridge designed for the workflow:

```text
ChatGPT / Codex / browser
        ↓
Remote MCP + upload gateway
        ↓
SFTP over SSH key
        ↓
Hostinger jailed destination root
```

It gives you **three interfaces over the same transfer core**:

1. **MCP** at `/mcp`
2. **Browser drop-zone** for large binary files
3. **CLI** via `hostinger-upload`

The browser route is important because a 100+ MB ZIP should **not** be base64-encoded
through an LLM tool call. The MCP tool issues a short-lived signed URL and the browser
streams the file directly to the bridge.

## Default destination

The included `.env.example` is prefilled for:

```text
SSH host: 82.29.199.248
SSH port: 65002
user: u365102102
root: /home/u365102102/domains/avatararts.org/public_html/gpt-export-rename
```

No password or private key is included.

## Security model

- SSH private-key authentication only
- host-key verification with `known_hosts`
- all remote paths jailed beneath `HFB_REMOTE_ROOT`
- traversal/absolute paths rejected
- browser upload URLs are HMAC-signed and expire
- uploads go to `*.uploading` before atomic rename
- optional expected size and SHA-256 verification
- overwrite is off by default
- ZIP symlinks are rejected
- directory deletion is intentionally not exposed
- source URLs must use HTTPS

## Tools

| Tool | Mutates? | Purpose |
|---|---:|---|
| `remote_status` | No | Test SSH/SFTP and configured root |
| `list_remote` | No | Browse destination |
| `mkdir_remote` | Yes | Create directory |
| `upload_text` | Yes | Small text/JSON/Markdown |
| `create_browser_upload` | Ticket only | Issue a large-file drop URL |
| `upload_from_url` | Yes | Pull from trusted HTTPS URL |
| `extract_remote_zip` | Yes | Safe ZIP extraction beneath root |
| `delete_remote` | Destructive | Delete one file only |

## Quick start

```bash
cp .env.example .env
# edit secrets and paths

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest

hostinger-file-bridge
```

MCP will be available at:

```text
http://127.0.0.1:8000/mcp
```

For deployment, put HTTPS and authentication in front of it.

## Capture and verify the SSH host key

Do this on a trusted machine where you can verify the Hostinger fingerprint:

```bash
ssh-keyscan -p 65002 82.29.199.248 > known_hosts
ssh-keygen -lf known_hosts
```

Compare the fingerprint with Hostinger's trusted account/server information before use.
Then mount that file into the service and set:

```bash
HFB_KNOWN_HOSTS_PATH=/run/secrets/known_hosts
```

## CLI upload

```bash
hostinger-upload upload \
  ~/Downloads/AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip \
  releases/AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip
```

No `scp` executable is needed. Paramiko speaks SFTP directly.

## ChatGPT usage

A custom ChatGPT app can point to the deployed `/mcp` endpoint.

A good large-file flow is:

```text
"Prepare an upload for AvatarArts-CreativeOS-Memory-Product-2026-08-18.zip"
      ↓
create_browser_upload(...)
      ↓
short-lived HTTPS URL
      ↓
open URL, choose the ZIP
      ↓
server streams + hashes + SFTP uploads
      ↓
list_remote / remote_status verifies result
```

See `docs/CHATGPT_SETUP.md`.

## Why not put SSH credentials in ChatGPT?

Because the MCP server should be the credential boundary. ChatGPT should invoke a narrow
tool like:

```text
create_browser_upload(relative_path=...)
```

It should never receive your private SSH key or password.
