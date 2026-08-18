# Deployment

## Option A: Run on a VPS / app host

This is the simplest remote-MCP deployment.

Requirements:
- Python 3.11+
- outbound TCP access to `82.29.199.248:65002`
- HTTPS reverse proxy
- mounted SSH private key
- mounted verified `known_hosts`
- secret upload-signing key

Start:

```bash
pip install .
hostinger-file-bridge
```

Reverse proxy `/mcp` and `/drop/*` behind HTTPS.

## Option B: Run on the Hostinger account itself

If the Hostinger plan supports a persistent Python/ASGI process, you can run the bridge
on the same account. It can still use SFTP back to the account, but a future optimization
can add a local-filesystem backend jailed to the same root.

Do **not** assume shared hosting permits a persistent daemon. Verify plan capabilities.

## Docker

```bash
docker build -t hostinger-file-bridge .
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v "$PWD/secrets/id_ed25519:/run/secrets/hostinger_ed25519:ro" \
  -v "$PWD/secrets/known_hosts:/run/secrets/known_hosts:ro" \
  hostinger-file-bridge
```

## Reverse proxy

Recommended:
- HTTPS only
- auth in front of browser pages
- request size comfortably above your largest ZIP
- long upload timeout
- rate limiting
- access logs without credentials/tokens
