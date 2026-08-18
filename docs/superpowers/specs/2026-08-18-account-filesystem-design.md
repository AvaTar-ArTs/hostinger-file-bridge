# Hostinger File Bridge — Account Filesystem Architecture Design

## Status

Approved architecture direction: **C+ hybrid account filesystem**.

This design replaces the current single-root model with an account-scoped remote filesystem abstraction that supports named aliases for convenience and explicit absolute-path access for power users, while preserving strong credential isolation, host-key verification, operation-specific approvals, dry runs, and auditable behavior.

## Why this change

The current implementation hardcodes one deep destination root:

```text
/home/u365102102/domains/avatararts.org/public_html/gpt-export-rename
```

That solved the first upload use case safely, but it unnecessarily constrains the utility. The authenticated Hostinger SSH/SFTP account already defines the real access ceiling. The bridge should model the account’s accessible filesystem rather than pretending one project directory is the whole server.

The revised model therefore treats named locations as **bookmarks/aliases, not security sandboxes**.

## Goals

1. Provide access to the full filesystem visible to the authenticated SSH account.
2. Preserve safe, ergonomic named aliases for frequently used locations.
3. Support home-relative, alias-relative, and explicit absolute paths.
4. Detect whether a connection supports SFTP only or both SFTP and SSH shell execution.
5. Use SFTP as the portable file-transfer baseline and shell commands only when capabilities are explicitly detected.
6. Add first-class copy, move, find, archive, checksum, disk-usage, and sync workflows.
7. Add operation-specific risk levels, dry runs, previews, and approval requirements.
8. Keep secrets behind the bridge rather than passing passwords or keys through MCP arguments.
9. Keep the MCP tool surface compact and semantic.
10. Make the internal architecture reusable for additional SFTP/SSH hosts later.

## Non-goals

- Do not expose an unrestricted arbitrary shell-execution MCP tool.
- Do not treat MCP Roots as the security boundary.
- Do not store SSH private keys, passwords, passphrases, or upload-signing secrets in source control.
- Do not silently follow symlinks during recursive traversal, sync, archive, or destructive operations.
- Do not make recursive deletion a one-step operation.
- Do not assume every Hostinger plan exposes identical shell commands or capabilities.

## Core architecture

```text
                    HOSTINGER FILE BRIDGE
                              |
                 Connection / Credential Layer
                              |
            +-----------------+-----------------+
            |                                   |
          SFTP                                SSH shell
            |                                   |
   portable file operations          accelerated server operations
            |                                   |
            +-----------------+-----------------+
                              |
                       Capability Engine
                              |
                        Path Resolver
                home / alias / absolute
                              |
                         Policy Engine
                operation + risk + approval
                              |
                       Filesystem Core
                              |
       +--------------+-------+---------+-------------+
       |              |                 |             |
      MCP            CLI              REST       Browser Drop
```

## Connection model

A connection represents one SSH/SFTP account.

Example configuration:

```yaml
connections:
  hostinger-main:
    host: 82.29.199.248
    port: 65002
    username: u365102102
    auth: key_file
    home: auto
    known_hosts: /run/secrets/known_hosts

    aliases:
      home: .
      domains: domains
      avatararts: domains/avatararts.org
      avatararts-web: domains/avatararts.org/public_html
      openai-gpt: domains/avatararts.org/public_html/openai-gpt
      gpt-exports: domains/avatararts.org/public_html/gpt-export-rename
```

The bridge may support more connections later without changing the filesystem core.

## Authentication hierarchy

Supported credential modes, in preference order:

1. SSH agent
2. mounted key file
3. secret-managed private-key material
4. secret-managed password

MCP arguments must never accept raw passwords or private keys.

The bridge configuration may identify a secret reference, but secret resolution belongs to the deployment environment.

## Host-key verification

Strict host-key verification remains mandatory by default.

Unknown host keys are rejected unless an administrator explicitly configures a controlled enrollment flow outside normal MCP filesystem calls.

The bridge must never silently fall back to accepting unknown host keys.

## Capability discovery

On connection, the bridge should discover and cache a capability snapshot such as:

```json
{
  "sftp": true,
  "shell": true,
  "home": "/home/u365102102",
  "commands": {
    "cp": true,
    "mv": true,
    "find": true,
    "du": true,
    "tar": true,
    "zip": true,
    "unzip": true,
    "sha256sum": true,
    "rsync": true
  }
}
```

Capability discovery must be conservative:

- a command is available only if positively detected;
- shell absence must not break baseline SFTP functions;
- every accelerated operation needs a portable fallback where practical;
- the capability snapshot should be inspectable by users/agents.

## Path model

Every filesystem operation uses a structured path specification.

```json
{
  "connection": "hostinger-main",
  "base": "avatararts-web",
  "path": "assets/releases/file.zip",
  "follow_symlinks": false
}
```

### Base modes

`home`
: Resolve relative to the authenticated account home.

`<alias>`
: Resolve relative to a configured alias/bookmark.

`absolute`
: Use the supplied absolute path directly, subject to SSH-account permissions and policy checks.

### Important invariant

```text
aliases != permissions
```

Aliases exist for convenience and discoverability. The real access ceiling is what the authenticated account can access.

### Normalization

For home/alias-relative paths:

- normalize separators;
- reject NUL bytes;
- resolve `.` and `..` safely;
- do not allow traversal above the selected base;
- preserve the ability to intentionally select a broader base instead of using traversal as an escape mechanism.

For absolute paths:

- require `base="absolute"` explicitly;
- require an absolute path;
- normalize the path;
- apply policy/risk checks before mutation;
- rely on remote account permissions as the final access boundary.

## Symlink policy

Default:

```text
follow_symlinks = false
```

for:

- recursive list/find;
- recursive copy;
- sync;
- archive creation;
- extraction overwrite decisions;
- recursive delete;
- disk-usage traversal.

Individual `stat`, `read`, or explicitly requested operations may opt into following symlinks.

When symlinks are encountered during recursive operations, the result should report them rather than silently traversing them.

## Backend selection

SFTP is the baseline backend.

Shell execution is an optimization layer, not the canonical API.

Examples:

### Copy

If shell + `cp` is available:

```text
server-side copy
```

Otherwise:

```text
SFTP stream source -> bridge -> SFTP destination
```

### Checksum

If shell + `sha256sum` is available:

```text
remote checksum
```

Otherwise:

```text
stream remote file over SFTP and hash client-side
```

### Sync

If shell + `rsync` is positively detected and the operation is same-host:

```text
rsync plan/execute
```

Otherwise:

```text
manifest comparison + differential SFTP transfer
```

The caller should receive the selected strategy in the result metadata.

## Filesystem service layer

The internal service should expose focused primitives rather than MCP-specific functions.

Recommended internal components:

```text
connections.py
  connection config, auth strategy, session lifecycle

capabilities.py
  SFTP/shell/command capability discovery

paths.py
  PathSpec, aliases, normalization, resolution

policy.py
  operation risk classification and approval requirements

sftp_backend.py
  portable file operations

shell_backend.py
  constrained command templates for accelerated operations

filesystem.py
  semantic filesystem service

archives.py
  safe create/inspect/extract workflows

sync.py
  planning, diffing, rsync/SFTP strategies

transfers.py
  browser upload, URL import, download tickets

server.py
  MCP + HTTP transport adapters

cli.py
  CLI adapter over the same filesystem service
```

No backend should accept arbitrary shell command strings from users or MCP models.

## MCP surface

Keep the MCP interface small enough for reliable tool selection.

Recommended tools:

### `fs_connections`

Use for:

- list connections;
- inspect aliases;
- inspect capabilities;
- connection health/status.

Read-only.

### `fs_list`

List one directory.

Inputs include:

- PathSpec;
- optional hidden-file inclusion;
- optional lightweight metadata.

Read-only.

### `fs_stat`

Inspect one path.

Return:

- type;
- size;
- timestamps;
- permissions/mode where available;
- symlink metadata;
- checksum only when requested.

Read-only.

### `fs_find`

Recursive/search-oriented discovery.

Inputs may include:

- glob/name pattern;
- type filters;
- max depth;
- size bounds;
- mtime bounds;
- follow_symlinks=false by default.

Read-only.

### `fs_read`

Read or download file content/metadata.

For large files, return a download-ticket flow instead of embedding binary data into MCP JSON.

Read-only.

### `fs_write`

Small text/binary-safe writes and explicit overwrite behavior.

Large browser uploads should route through `fs_transfer`.

Mutating.

### `fs_transfer`

Operations:

- browser_upload;
- upload;
- download;
- url_import;
- remote_to_remote.

The browser-upload path remains the preferred large-file path for ChatGPT-style environments.

### `fs_manage`

Operations:

- mkdir;
- touch;
- rename;
- move;
- copy;
- chmod;
- delete.

The operation enum determines risk and required approval.

### `fs_archive`

Operations:

- inspect;
- create;
- extract.

Safe extraction must reject path traversal and unsafe symlink behavior.

### `fs_sync`

Plan and execute directory synchronization.

Inputs include:

- source PathSpec;
- destination PathSpec;
- direction;
- overwrite policy;
- deletion policy;
- dry_run;
- checksum policy.

`sync --delete` behavior must be treated as high-impact destructive work.

## Risk model

### Level 0 — read-only

Examples:

- list;
- stat;
- find;
- read;
- checksum;
- capability discovery.

No additional application-level confirmation required.

### Level 1 — additive mutation

Examples:

- mkdir;
- upload to new path;
- create archive;
- copy to new path.

Normal MCP write approval semantics apply.

### Level 2 — replacement/mutation

Examples:

- overwrite;
- move;
- rename over existing target;
- chmod;
- extract over existing files.

Require explicit approval metadata and a clear preview of affected targets.

### Level 3 — destructive

Examples:

- delete one file;
- delete empty directory.

Require explicit approval and exact target echo.

### Level 4 — high-impact destructive

Examples:

- recursive directory delete;
- sync with destination deletion;
- bulk delete;
- archive extraction that replaces many existing files.

Required preflight result:

```json
{
  "operation": "recursive_delete",
  "target": "/home/u365102102/example",
  "files": 482,
  "directories": 37,
  "estimated_bytes": 816240032,
  "approval_required": true,
  "approval_scope": "exact-operation-plan"
}
```

Execution must require an approval tied to the generated plan fingerprint so the target cannot change between preview and execution.

## Dry-run model

Complex or destructive operations should support:

```text
dry_run = true
```

including:

- copy trees;
- move trees;
- archive extraction;
- recursive delete;
- sync;
- bulk permission changes.

Dry-run output should be machine-readable and contain:

- planned operations;
- counts;
- estimated bytes;
- conflicts;
- symlink encounters;
- selected backend strategy;
- risk level;
- approval requirement;
- plan fingerprint.

## Plan fingerprints

A destructive/high-impact plan should be hashed from canonical operation inputs and relevant discovered targets.

Execution accepts the fingerprint rather than merely repeating `confirm=true`.

This prevents an approval from being reused after the target set changes.

## Archive safety

Archive extraction must:

- reject absolute member paths;
- reject `..` traversal;
- reject or explicitly quarantine symlink members by default;
- preflight collisions;
- support dry-run;
- enforce file-count and total-uncompressed-size limits;
- report suspicious compression ratios;
- never extract outside the requested destination.

Archive creation must not silently follow symlinks by default.

## URL import safety

URL import remains opt-in and constrained.

Requirements:

- HTTPS only by default;
- hostname allowlist or explicit administrator policy;
- resolve and reject loopback/private/link-local/metadata-network destinations;
- revalidate redirects;
- size cap;
- timeout;
- streaming hash;
- no credential forwarding to arbitrary hosts.

## Sync architecture

Sync is a first-class subsystem rather than a loop over upload.

### Plan phase

Build normalized source and destination manifests containing, as available:

- relative path;
- type;
- size;
- mtime;
- checksum when policy requires it;
- symlink metadata.

Classify entries:

- unchanged;
- create;
- update;
- conflict;
- delete candidate.

### Strategy selection

1. same host + shell + rsync available -> rsync strategy;
2. otherwise -> bridge-managed differential SFTP strategy.

### Delete semantics

Deletion is disabled by default.

When requested, deletion candidates are shown in the dry-run plan and require Level 4 approval.

## Browser upload/download flows

Large files should bypass MCP JSON payloads.

### Browser upload

```text
MCP fs_transfer(browser_upload)
  -> signed short-lived upload URL
  -> browser streams file to bridge
  -> bridge verifies size/hash
  -> remote transfer
  -> final stat/hash result
```

### Download ticket

For large remote downloads:

```text
MCP fs_read / fs_transfer(download)
  -> short-lived signed URL
  -> bridge streams from SFTP to browser
```

Tickets must expire and be scoped to one canonical path and operation.

## Multiple domains and aliases

Aliases should be configurable without code changes.

Examples:

```yaml
aliases:
  domains: domains
  avatararts: domains/avatararts.org
  avatararts-web: domains/avatararts.org/public_html
  gptjunkie: domains/gptjunkie.com
  openai-gpt: domains/avatararts.org/public_html/openai-gpt
  gpt-exports: domains/avatararts.org/public_html/gpt-export-rename
```

Aliases may be listed through `fs_connections` so agents can discover useful locations.

## Migration from v0.1

The migration must preserve backwards compatibility long enough for existing callers to move cleanly.

### Current model

```text
HFB_REMOTE_ROOT=/home/.../gpt-export-rename
list_remote(relative_dir)
mkdir_remote(relative_dir)
upload_text(relative_path,...)
extract_remote_zip(...)
```

### New model

```text
HFB_DEFAULT_CONNECTION=hostinger-main
HFB_DEFAULT_BASE=home
connections + aliases
PathSpec
fs_*
```

### Compatibility adapter

For one compatibility release, old tools may map to:

```text
connection = default connection
base = legacy-root alias
path = existing relative path
```

Mark old tool names deprecated in MCP descriptions and docs.

Do not remove them until the new interface has fixtures/tests and one release cycle of usage.

## Configuration direction

Move beyond a single flat `.env` for complex location definitions.

Recommended split:

```text
.env
  secret references / deployment-specific values

config/connections.yaml
  connection metadata and alias definitions

/run/secrets/*
  private keys, passwords, known_hosts, signing secrets
```

Environment variables may override config for container deployment.

## Auditing and observability

Every mutation should emit an audit event containing:

- timestamp;
- connection;
- resolved source/destination paths;
- requested operation;
- selected backend strategy;
- risk level;
- dry-run or execute;
- plan fingerprint if applicable;
- byte/file counts;
- success/failure;
- resulting checksum where practical.

Never log secret material or upload-ticket secrets.

## Error model

Use typed domain errors rather than leaking backend exceptions directly.

Examples:

- `ConnectionUnavailable`
- `AuthenticationFailed`
- `HostKeyRejected`
- `PathResolutionError`
- `PermissionDenied`
- `CapabilityUnavailable`
- `ConflictError`
- `ApprovalRequired`
- `PlanChanged`
- `ArchiveSafetyError`
- `TransferIntegrityError`

MCP/CLI adapters translate these into user-facing structured errors.

## Testing strategy

### Unit tests

- path normalization for home/alias/absolute modes;
- alias resolution;
- traversal rejection within alias/home bases;
- absolute-mode validation;
- symlink default behavior;
- risk classification;
- plan fingerprint stability/change detection;
- archive traversal/symlink/zip-bomb defenses;
- URL SSRF controls;
- capability strategy selection;
- sync manifest diffing.

### Integration tests

Use a local ephemeral SSH/SFTP fixture/container to test:

- key authentication;
- password-secret authentication;
- host-key rejection;
- uploads/downloads;
- server-side/fallback copy;
- archive flows;
- sync;
- permissions;
- symlinks.

### Live Hostinger tests

Live tests are opt-in and secret-gated.

They must operate only inside a dedicated test directory and clean up after themselves.

They must never run destructive tests against production site roots.

## Documentation changes

README should lead with the broad model:

> Hostinger File Bridge is an account-scoped SSH/SFTP filesystem bridge for ChatGPT, Codex, browser workflows, and CLI automation.

The old `gpt-export-rename` location should appear only as one example alias, not as the product’s defining root.

Docs should include:

- connection setup;
- alias setup;
- absolute-path power mode;
- permissions and approvals;
- browser upload/download;
- sync examples;
- archive examples;
- migration from v0.1;
- security model;
- deployment.

## Versioning

This architectural change should ship as **v0.2.0** because it changes the public tool/path model while retaining a compatibility bridge for the v0.1 calls.

## Acceptance criteria

The v0.2 implementation is complete when all of the following are true:

1. A caller can browse the SSH account home without a hardcoded deep root.
2. A caller can use named aliases such as `avatararts-web` and `openai-gpt`.
3. A caller can explicitly address an absolute path allowed by the SSH account.
4. SFTP-only mode remains fully functional for baseline operations.
5. Shell capabilities are detected rather than assumed.
6. Copy/checksum/sync select accelerated or fallback strategies deterministically.
7. Large upload and download flows avoid embedding binaries in MCP JSON.
8. Recursive/destructive operations provide dry-run previews and plan fingerprints.
9. `sync --delete` and recursive delete cannot execute without Level 4 approval.
10. Recursive operations do not follow symlinks by default.
11. Archive extraction is traversal-safe and preflighted.
12. URL import remains SSRF-hardened.
13. Existing v0.1 tool names continue working through a documented deprecated adapter for one release cycle.
14. Unit and integration tests cover the new path/policy/backend model.
15. README and deployment docs no longer present `gpt-export-rename` as the filesystem boundary.

## Final recommendation

Build **C+ hybrid account-filesystem architecture**:

```text
full SSH-visible account
+
home-relative paths
+
named aliases/bookmarks
+
explicit absolute-path mode
+
SFTP baseline
+
SSH capability acceleration
+
dry-run + approval policy
+
compact semantic MCP interface
```

This preserves the utility’s safety while removing the artificial location restriction that made v0.1 too narrow.
