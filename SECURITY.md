# Security Policy

## Credential rules

Never put any of these in:
- MCP tool arguments
- ChatGPT messages
- source control
- logs
- screenshots

Secrets:
- SSH private key
- SSH password
- private-key passphrase
- HMAC upload signing secret
- bearer tokens

Use mounted secret files / secret managers.

## Host-key verification

Unknown Hostinger SSH host keys are rejected.

Populate `HFB_KNOWN_HOSTS_PATH` with a key whose fingerprint you have independently
verified.

## Root jail

Every remote path is resolved beneath `HFB_REMOTE_ROOT`. Absolute paths, `~`, and `..`
traversal are rejected.

## Overwrites

Uploads default to `overwrite=false`. A write uses an `.uploading` temporary path and is
renamed after validation.

## Large file transfers

Use `create_browser_upload`, not base64 in tool calls.

## ZIP extraction

ZIP members are normalized and symlinks rejected. Every member is uploaded through the
same root-jail logic.
