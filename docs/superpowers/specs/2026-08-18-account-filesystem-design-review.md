# Hostinger File Bridge — Account Filesystem Design Review

**Status:** Normative review addendum. This document amends `2026-08-18-account-filesystem-design.md` and is part of the approved v0.2.0 specification. Where this addendum is more specific, it takes precedence.

## Review result

The C+ account-filesystem architecture is approved after review. The core design is sound, but eight implementation details needed to be made explicit before planning.

## 1. SFTP and shell path namespaces

An SSH host may expose different apparent path namespaces through SFTP and an interactive shell. For example, an SFTP subsystem may present `/` as an account/chroot root while shell commands report `/home/<user>`.

The bridge must therefore discover and model both namespaces instead of assuming one textual absolute path works identically in both backends.

Each connection capability snapshot must include:

```json
{
  "home": "/home/u365102102",
  "sftp_home": ".",
  "shell_home": "/home/u365102102",
  "sftp_chrooted": true,
  "shell": true
}
```

`ResolvedPath` must carry backend-specific representations:

```text
ResolvedPath
├── connection_id
├── logical_path
├── sftp_path
├── shell_path | null
├── base_mode
├── alias | null
└── follow_symlinks
```

The filesystem service resolves a logical `PathSpec` once and hands the appropriate representation to each backend. Shell acceleration must never be attempted when a safe shell-path mapping cannot be proven.

## 2. Bounded read and discovery operations

Read-only must not mean unbounded.

Defaults, all configurable:

```yaml
limits:
  inline_read_bytes: 1048576       # 1 MiB
  find_max_results: 1000
  find_max_depth: 25
  find_timeout_seconds: 30
  directory_list_max_results: 5000
```

`fs_read` returns inline UTF-8/text content only when the result is at or below `inline_read_bytes`. Larger files use a download ticket or explicit streamed transfer.

`fs_find` must stop at the first configured bound reached and return `truncated=true` with the reason (`max_results`, `max_depth`, or `timeout`).

## 3. Concurrency and atomic mutation

Mutating operations must use a destination-scoped lock inside the bridge so two requests cannot simultaneously overwrite/rename the same destination.

Uploads and generated files use a unique temporary sibling name:

```text
.<basename>.hfb-<operation-id>.partial
```

The final destination is changed only after transfer and integrity validation succeed.

Cross-filesystem/server rename may not be atomic. The selected strategy and atomicity guarantee must be reported in result metadata:

```json
{
  "atomic": true,
  "strategy": "sftp-temp-rename"
}
```

A failed operation must make a best-effort cleanup of its own temporary artifacts without deleting pre-existing user files.

## 4. Approval plans and fingerprints

All Level 2, Level 3, and Level 4 mutations use a two-phase preflight/execute contract when they can replace, remove, or recursively alter existing content.

A preflight plan contains:

```text
plan_id
operation
canonical inputs
resolved paths
target snapshot metadata
planned actions
risk level
created_at
expires_at
fingerprint
```

Default plan lifetime: **10 minutes**.

The fingerprint is SHA-256 over a canonical serialized representation of:

- operation and options;
- connection and resolved source/destination identities;
- planned target set;
- relevant size/mtime/mode metadata;
- symlink identities;
- plan creation nonce.

Execution requires both `plan_id` and `fingerprint`. Before execution the bridge revalidates the target snapshot. Any relevant change returns `PlanChanged` and requires a new preflight.

Level 1 additive operations may execute directly when the destination is proven absent. If the destination appears between check and write, the operation fails with `ConflictError`; it must not silently escalate to overwrite.

## 5. Archive safety defaults

Archive limits are configurable with these defaults:

```yaml
archive_limits:
  max_members: 100000
  max_total_uncompressed_bytes: 5368709120   # 5 GiB
  max_single_member_bytes: 2147483648         # 2 GiB
  suspicious_compression_ratio: 1000
```

Crossing a hard size/member limit fails before extraction when metadata makes preflight possible, or as soon as the streamed limit is exceeded.

A compression ratio at or above the suspicious threshold is reported and requires explicit Level 2 approval rather than being silently accepted.

Archive extraction never materializes absolute paths, `..` traversal, device files, FIFOs, or symlink/hardlink members by default.

## 6. Transfer tickets

Browser upload and download tickets are:

- HMAC-signed;
- operation-scoped;
- canonical-path-scoped;
- short-lived;
- **single-use by default**;
- revocable by deleting their server-side ticket record;
- never logged in full.

Default lifetime remains 15 minutes unless configured otherwise.

Ticket state may be stored in memory for a single-process deployment. Multi-worker or horizontally scaled deployments require a shared ticket store before scaling beyond one process.

## 7. Audit persistence

Mutation audit events must be persisted, not only emitted to stdout.

Default local sink:

```text
data/audit.jsonl
```

Each event is append-only JSON with an `event_id`, timestamp, operation id, connection id, resolved logical paths, risk level, strategy, dry-run/execute state, plan/fingerprint prefix, counts, outcome, and error code where applicable.

Secrets, full signed tickets, passwords, private keys, passphrases, and raw authorization headers are prohibited from audit records.

The audit sink is replaceable so deployments can forward events to another store later.

## 8. Symlink semantics

The v0.2 filesystem API should support inspecting and intentionally creating links without making them invisible side effects.

Add:

- `fs_stat(..., follow_symlinks=false)` returns link target metadata where available;
- `fs_manage(operation="symlink", source=<target>, destination=<link>)` as Level 2;
- `fs_manage(operation="readlink", ...)` is read-only if exposed through `fs_manage`, though `fs_stat` should normally be sufficient.

Recursive operations continue to default to `follow_symlinks=false`.

A created symlink may point outside an alias because aliases are bookmarks, not permission boundaries. The preflight must show the resolved link target when it can be determined. The authenticated SSH account remains the ultimate access ceiling.

## Additional implementation invariants

- No arbitrary shell command MCP input.
- Every shell invocation uses a fixed command template plus separately quoted/validated arguments.
- When safe shell path mapping is unavailable, fall back to SFTP rather than guessing.
- Absolute-path mode must remain explicit.
- Legacy v0.1 calls remain compatibility adapters for the v0.2 release cycle.
- Public documentation must distinguish logical paths from backend-specific paths.
- Integration tests must include a chroot-like SFTP namespace fixture in addition to the normal SSH/SFTP fixture.

## Approval

With these amendments, the design is sufficiently specific to move to implementation planning. No production implementation changes are authorized by this document itself; implementation follows the separate v0.2.0 plan.
