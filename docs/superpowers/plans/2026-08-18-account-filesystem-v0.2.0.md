# Hostinger File Bridge v0.2.0 Account Filesystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v0.1 single-root SFTP bridge with the approved C+ account-scoped filesystem architecture while retaining a one-release compatibility adapter for existing v0.1 callers.

**Architecture:** Introduce a logical `PathSpec`/`ResolvedPath` model, multi-connection configuration, SFTP and constrained-shell backends, capability discovery, a policy/preflight layer, and semantic filesystem/archive/sync/transfer services. MCP, CLI, browser upload/download, and legacy tools become adapters over the same service layer. SFTP remains the portable baseline; shell execution is an optional acceleration path selected only when positively detected and safely mapped.

**Tech Stack:** Python 3.11+, MCP Python SDK, FastAPI/Starlette, Paramiko, Pydantic Settings, PyYAML, pytest, Docker/OpenSSH integration fixture, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-18-account-filesystem-design.md` plus normative addendum `docs/superpowers/specs/2026-08-18-account-filesystem-design-review.md`

## Global Constraints

- Version target: `0.2.0`.
- SFTP is the baseline backend; shell commands are acceleration only.
- Never accept arbitrary shell command strings from MCP, HTTP, or CLI callers.
- Unknown SSH host keys remain rejected by default.
- MCP arguments never accept raw passwords or private keys.
- Aliases are bookmarks, not permission boundaries.
- `base="absolute"` is required for absolute-path mode.
- Recursive traversal defaults to `follow_symlinks=false`.
- Level 2–4 replacement/destructive operations use preflight plans when existing content may be affected.
- Level 4 operations require `plan_id` + fingerprint and target revalidation.
- Default plan lifetime: 10 minutes.
- Inline read limit: 1 MiB.
- Default find limits: 1000 results, depth 25, timeout 30 seconds.
- Archive defaults: 100000 members, 5 GiB total uncompressed, 2 GiB single member, suspicious ratio 1000:1.
- Transfer tickets are operation/path scoped, expire after 15 minutes by default, and are single-use by default.
- Mutation audits persist to `data/audit.jsonl` by default and never contain secrets or complete signed tickets.
- v0.1 tool names remain available as deprecated adapters through the v0.2 release cycle.

---

## File Structure

### New focused modules

- `src/hostinger_file_bridge/models.py` — `PathSpec`, `ResolvedPath`, capability, result, operation-plan, and audit models.
- `src/hostinger_file_bridge/errors.py` — typed domain errors used by every adapter.
- `src/hostinger_file_bridge/connections.py` — connection config, authentication strategy, session lifecycle, home discovery.
- `src/hostinger_file_bridge/capabilities.py` — conservative SFTP/shell/command capability discovery and caching.
- `src/hostinger_file_bridge/paths.py` — logical path normalization, aliases, SFTP/shell namespace mapping.
- `src/hostinger_file_bridge/policy.py` — risk classification, preflight plans, fingerprints, plan expiration/revalidation.
- `src/hostinger_file_bridge/audit.py` — append-only JSONL mutation audit sink.
- `src/hostinger_file_bridge/sftp_backend.py` — portable SFTP primitives.
- `src/hostinger_file_bridge/shell_backend.py` — fixed-template shell accelerators only.
- `src/hostinger_file_bridge/filesystem.py` — semantic filesystem service selecting safe strategy.
- `src/hostinger_file_bridge/archives.py` — archive inspect/create/extract planning and safety checks.
- `src/hostinger_file_bridge/sync.py` — manifest construction, diffing, plan/execute strategies.
- `src/hostinger_file_bridge/transfers.py` — browser upload/download tickets, URL import, streaming transfer helpers.
- `config/connections.yaml.example` — non-secret multi-connection/alias configuration example.

### Existing modules to change

- `src/hostinger_file_bridge/config.py` — load deployment settings plus YAML connection definitions.
- `src/hostinger_file_bridge/security.py` — retain upload-token and SSRF utilities, add canonical serialization helpers where appropriate.
- `src/hostinger_file_bridge/sftp.py` — become v0.1 compatibility facade or be reduced to imports from the new backend/service.
- `src/hostinger_file_bridge/server.py` — register new compact `fs_*` MCP tools and HTTP ticket endpoints; keep deprecated tools.
- `src/hostinger_file_bridge/cli.py` — expose new path/connection model while retaining simple legacy commands.
- `pyproject.toml` — add PyYAML and bump version to 0.2.0.
- `.env.example`, `README.md`, `SECURITY.md`, `docs/DEPLOY.md`, `docs/CHATGPT_SETUP.md`, `CHANGELOG.md` — document account-scoped model and migration.
- `.github/workflows/ci.yml` — add integration fixture lane.

### New tests

- `tests/test_models.py`
- `tests/test_paths.py`
- `tests/test_connections.py`
- `tests/test_capabilities.py`
- `tests/test_policy.py`
- `tests/test_audit.py`
- `tests/test_filesystem.py`
- `tests/test_archives.py`
- `tests/test_sync.py`
- `tests/test_transfers.py`
- `tests/test_legacy_adapter.py`
- `tests/integration/test_ssh_sftp.py`
- `tests/integration/ssh_fixture/Dockerfile`
- `tests/integration/ssh_fixture/sshd_config`

---

### Task 1: Domain Models, Typed Errors, and Connection Configuration

**Files:**
- Create: `src/hostinger_file_bridge/models.py`
- Create: `src/hostinger_file_bridge/errors.py`
- Modify: `src/hostinger_file_bridge/config.py`
- Create: `config/connections.yaml.example`
- Modify: `pyproject.toml`
- Test: `tests/test_models.py`
- Test: `tests/test_connections.py`

**Interfaces:**
- Produces: `PathSpec`, `ResolvedPath`, `ConnectionDefinition`, `ConnectionCapabilities`, `RiskLevel`, `OperationPlan`, `MutationResult`, `AuditEvent`.
- Produces: `BridgeError` subclasses `ConnectionUnavailable`, `AuthenticationFailed`, `HostKeyRejected`, `PathResolutionError`, `PermissionDenied`, `CapabilityUnavailable`, `ConflictError`, `ApprovalRequired`, `PlanChanged`, `ArchiveSafetyError`, `TransferIntegrityError`.
- Produces: `Settings.load_connections() -> dict[str, ConnectionDefinition]`.

- [ ] **Step 1: Write failing model/config tests**

```python
from hostinger_file_bridge.models import PathSpec, RiskLevel


def test_pathspec_requires_explicit_absolute_base():
    p = PathSpec(connection="hostinger-main", base="absolute", path="/home/u/file.txt")
    assert p.base == "absolute"


def test_risk_levels_are_ordered():
    assert RiskLevel.READ_ONLY < RiskLevel.ADDITIVE < RiskLevel.REPLACEMENT < RiskLevel.DESTRUCTIVE < RiskLevel.HIGH_IMPACT
```

Add a YAML-loading test that writes a temporary `connections.yaml` with `hostinger-main` and aliases, then asserts `Settings.load_connections()` returns those definitions without any credential bytes embedded in the YAML object.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_models.py tests/test_connections.py -v`
Expected: FAIL because the new model/config interfaces do not exist.

- [ ] **Step 3: Implement models/errors and YAML loading**

Use Pydantic models with explicit fields. `ConnectionDefinition` contains host, port, username, auth mode, secret references, known-hosts path, home mode, and aliases. Secret material remains in environment/secret files, not YAML values.

Add `PyYAML>=6.0.2` to dependencies and bump project version to `0.2.0`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_models.py tests/test_connections.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml config src/hostinger_file_bridge/models.py src/hostinger_file_bridge/errors.py src/hostinger_file_bridge/config.py tests/test_models.py tests/test_connections.py
git commit -m "feat: add v0.2 connection and filesystem domain models"
```

---

### Task 2: Logical Path Resolver and Dual Backend Namespace Mapping

**Files:**
- Create: `src/hostinger_file_bridge/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `PathSpec`, `ResolvedPath`, `ConnectionDefinition`, `ConnectionCapabilities`.
- Produces: `PathResolver.resolve(spec: PathSpec, definition: ConnectionDefinition, capabilities: ConnectionCapabilities) -> ResolvedPath`.
- Produces: `normalize_relative_path(value: str) -> str` and `normalize_absolute_path(value: str) -> str`.

- [ ] **Step 1: Write failing path tests**

Cover:

```python
def test_alias_relative_path_cannot_escape_alias(): ...
def test_home_path_can_select_domains_without_hardcoded_root(): ...
def test_absolute_requires_leading_slash(): ...
def test_sftp_chroot_and_shell_home_get_distinct_paths(): ...
def test_shell_path_is_none_when_mapping_cannot_be_proven(): ...
def test_nul_is_rejected(): ...
```

Required chroot case:

```python
caps = ConnectionCapabilities(
    sftp=True,
    shell=True,
    home="/home/u365102102",
    sftp_home=".",
    shell_home="/home/u365102102",
    sftp_chrooted=True,
    commands={},
)
spec = PathSpec(connection="hostinger-main", base="home", path="domains/avatararts.org")
r = resolver.resolve(spec, definition, caps)
assert r.sftp_path == "domains/avatararts.org"
assert r.shell_path == "/home/u365102102/domains/avatararts.org"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_paths.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement resolver**

Do not use alias-root jailing as the account security boundary. Prevent `..` from escaping only the explicitly selected home/alias base. Absolute mode normalizes and preserves account-visible paths. Resolver must not probe the server itself.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_paths.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/paths.py tests/test_paths.py
git commit -m "feat: add account-scoped path resolver"
```

---

### Task 3: Connection Lifecycle and Capability Discovery

**Files:**
- Create: `src/hostinger_file_bridge/connections.py`
- Create: `src/hostinger_file_bridge/capabilities.py`
- Test: `tests/test_connections.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Produces: `ConnectionManager.session(connection_id: str)` context manager returning an object with SSH client, SFTP client, and discovered namespaces.
- Produces: `CapabilityDetector.detect(session) -> ConnectionCapabilities`.
- Produces: cached capabilities keyed by connection id + host-key fingerprint with configurable TTL.

- [ ] **Step 1: Add failing auth/capability tests**

Use fakes, not a real host, to test:

```python
def test_unknown_host_key_is_never_autoaccepted(): ...
def test_agent_auth_precedes_key_and_password(): ...
def test_shell_failure_still_reports_sftp_true(): ...
def test_command_only_true_after_positive_detection(): ...
def test_capability_cache_is_keyed_by_host_key_identity(): ...
```

- [ ] **Step 2: Verify failures**

Run: `pytest tests/test_connections.py tests/test_capabilities.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement manager/detector**

Authentication preference: SSH agent → mounted key file → secret-managed key material → secret-managed password. Never log credentials. Detect shell with a constrained probe and commands with fixed `command -v <known-name>` templates only. Discover SFTP cwd/home and shell `$HOME` separately.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_connections.py tests/test_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/connections.py src/hostinger_file_bridge/capabilities.py tests/test_connections.py tests/test_capabilities.py
git commit -m "feat: discover ssh sftp capabilities safely"
```

---

### Task 4: Policy Engine, Preflight Plans, Fingerprints, and Audit Sink

**Files:**
- Create: `src/hostinger_file_bridge/policy.py`
- Create: `src/hostinger_file_bridge/audit.py`
- Test: `tests/test_policy.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Produces: `PolicyEngine.classify(operation, context) -> RiskLevel`.
- Produces: `PlanStore.create(...) -> OperationPlan`, `PlanStore.validate(plan_id, fingerprint, current_snapshot) -> OperationPlan`.
- Produces: `AuditSink.append(event: AuditEvent) -> None`.

- [ ] **Step 1: Write failing policy tests**

Required cases:

```python
def test_new_file_upload_is_level_one(): ...
def test_overwrite_is_level_two(): ...
def test_single_delete_is_level_three(): ...
def test_recursive_delete_and_sync_delete_are_level_four(): ...
def test_plan_fingerprint_changes_when_target_snapshot_changes(): ...
def test_plan_expires_after_ten_minutes(): ...
def test_level_one_conflict_does_not_auto_escalate(): ...
```

Audit test must assert strings resembling passwords, private-key material, and full signed tickets are redacted/rejected before writing `audit.jsonl`.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_policy.py tests/test_audit.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement deterministic canonical plan serialization**

Use sorted-key JSON with normalized path identities and target metadata, plus a random plan nonce. Default in-memory plan store is acceptable for single-process v0.2; make the storage interface replaceable.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy.py tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/policy.py src/hostinger_file_bridge/audit.py tests/test_policy.py tests/test_audit.py
git commit -m "feat: add mutation policy plans and audit log"
```

---

### Task 5: Portable SFTP Backend, Constrained Shell Backend, and Filesystem Core

**Files:**
- Create: `src/hostinger_file_bridge/sftp_backend.py`
- Create: `src/hostinger_file_bridge/shell_backend.py`
- Create: `src/hostinger_file_bridge/filesystem.py`
- Modify: `src/hostinger_file_bridge/sftp.py`
- Test: `tests/test_filesystem.py`

**Interfaces:**
- `SFTPBackend`: list, lstat/stat, read stream, write-temp-and-rename, mkdir, rename, remove, chmod, symlink/readlink, streamed copy/checksum.
- `ShellBackend`: only fixed operations `copy`, `move`, `find`, `du`, `checksum`, `archive`, `rsync_plan`, `rsync_execute`; arguments are individually validated/quoted and no public `exec(command: str)` exists.
- `FilesystemService`: `list`, `stat`, `find`, `read`, `write`, `manage`, `checksum`, `disk_usage`.

- [ ] **Step 1: Write failing strategy and atomicity tests**

Use fake backends to assert:

```python
def test_copy_prefers_shell_cp_only_when_capability_and_shell_path_exist(): ...
def test_copy_falls_back_to_streamed_sftp(): ...
def test_checksum_falls_back_to_sftp_stream(): ...
def test_write_uses_unique_partial_then_rename(): ...
def test_concurrent_destination_lock_prevents_two_overwrites(): ...
def test_recursive_find_defaults_to_not_follow_links(): ...
def test_large_read_returns_transfer_required_instead_of_inline_bytes(): ...
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_filesystem.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement backends/service**

Move portable logic out of the current monolithic `sftp.py`. Keep `sftp.py` as a compatibility facade importing the new service/backend where needed. Report `strategy` and `atomic` metadata for every mutation.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_filesystem.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/sftp_backend.py src/hostinger_file_bridge/shell_backend.py src/hostinger_file_bridge/filesystem.py src/hostinger_file_bridge/sftp.py tests/test_filesystem.py
git commit -m "feat: add account filesystem service and backends"
```

---

### Task 6: Transfer Tickets, Browser Upload/Download, and URL Import

**Files:**
- Create: `src/hostinger_file_bridge/transfers.py`
- Modify: `src/hostinger_file_bridge/security.py`
- Test: `tests/test_transfers.py`

**Interfaces:**
- Produces: `TransferTicketStore.issue_upload(...)`, `issue_download(...)`, `consume(token)`.
- Produces: `TransferService.browser_upload_ticket`, `download_ticket`, `url_import`, `remote_to_remote`.

- [ ] **Step 1: Write failing ticket/SSRF tests**

Cover:

```python
def test_ticket_is_single_use(): ...
def test_ticket_is_bound_to_operation_and_canonical_path(): ...
def test_ticket_expires(): ...
def test_private_resolution_is_rejected(): ...
def test_redirect_is_revalidated(): ...
def test_url_import_requires_allowlist_by_default(): ...
def test_streaming_size_limit_aborts_without_finalizing_destination(): ...
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_transfers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement transfer service**

Keep the existing HMAC concept but add server-side single-use state. Never log full tokens. Large downloads stream SFTP → HTTP response. Large uploads stream HTTP → temporary local/remote pipeline without MCP JSON embedding.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_transfers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/transfers.py src/hostinger_file_bridge/security.py tests/test_transfers.py
git commit -m "feat: add scoped one-time transfer tickets"
```

---

### Task 7: Safe Archive Subsystem

**Files:**
- Create: `src/hostinger_file_bridge/archives.py`
- Test: `tests/test_archives.py`

**Interfaces:**
- Produces: `ArchiveService.inspect`, `plan_create`, `create`, `plan_extract`, `extract`.
- Consumes: filesystem service, policy engine, archive-limit settings.

- [ ] **Step 1: Write failing malicious-archive tests**

Generate fixtures in-memory for:

```python
def test_rejects_absolute_member(): ...
def test_rejects_dotdot_member(): ...
def test_rejects_symlink_and_device_members_by_default(): ...
def test_member_limit_is_enforced(): ...
def test_uncompressed_limit_is_enforced(): ...
def test_suspicious_ratio_requires_level_two_plan(): ...
def test_collision_preflight_lists_existing_targets(): ...
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_archives.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement safe planning/extraction**

Prefer shell archive acceleration only when the exact safe operation can be represented without bypassing preflight. Otherwise use bridge-managed streaming extraction. Safety validation always happens in the bridge even when execution is accelerated.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_archives.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/archives.py tests/test_archives.py
git commit -m "feat: add preflighted safe archive workflows"
```

---

### Task 8: First-Class Sync Engine

**Files:**
- Create: `src/hostinger_file_bridge/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Produces: `SyncManifest`, `SyncDiff`, `SyncService.plan(source, destination, options) -> OperationPlan`, `SyncService.execute(plan_id, fingerprint) -> MutationResult`.

- [ ] **Step 1: Write failing manifest/diff tests**

Cover create/update/unchanged/conflict/delete-candidate classification, checksum-policy differences, symlink reporting, and deterministic plan fingerprint.

Required safety tests:

```python
def test_delete_candidates_absent_when_delete_policy_disabled(): ...
def test_sync_delete_is_level_four(): ...
def test_changed_destination_after_plan_returns_plan_changed(): ...
def test_same_host_rsync_selected_only_when_detected_and_safe_mapping_exists(): ...
def test_sftp_diff_strategy_is_portable_fallback(): ...
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_sync.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement manifest/diff/strategy**

Never shell out to raw caller-provided rsync flags. Translate a fixed `SyncOptions` model into a constrained rsync template. Deletion remains false by default.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/sync.py tests/test_sync.py
git commit -m "feat: add planned differential sync engine"
```

---

### Task 9: MCP, HTTP, CLI, and v0.1 Compatibility Adapters

**Files:**
- Modify: `src/hostinger_file_bridge/server.py`
- Modify: `src/hostinger_file_bridge/cli.py`
- Test: `tests/test_legacy_adapter.py`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- MCP tools: `fs_connections`, `fs_list`, `fs_stat`, `fs_find`, `fs_read`, `fs_write`, `fs_transfer`, `fs_manage`, `fs_archive`, `fs_sync`.
- Deprecated adapters: `remote_status`, `list_remote`, `mkdir_remote`, `upload_text`, `create_browser_upload`, `upload_from_url`, `delete_remote`, `extract_remote_zip`.

- [ ] **Step 1: Write failing tool-contract tests**

Assert read/write/destructive annotations match the risk of each tool, `PathSpec` is exposed structurally, and legacy calls map to `connection=default`, `base=legacy-root`, existing relative path.

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_legacy_adapter.py tests/test_server_tools.py -v`
Expected: FAIL.

- [ ] **Step 3: Refactor adapters over services**

`server.py` must not instantiate backend-specific logic directly. MCP tools call service objects. HTTP `/drop/*` and `/download/*` consume transfer tickets. CLI accepts forms such as:

```bash
hostinger-upload list --connection hostinger-main --base avatararts-web assets/
hostinger-upload stat --base absolute /home/u365102102/domains/avatararts.org
hostinger-upload sync --source-base home --source src --dest-base avatararts-web --dest assets --dry-run
```

Keep old CLI forms where practical and print deprecation warnings.

- [ ] **Step 4: Run adapter tests and full unit suite**

Run: `pytest tests -m "not integration" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hostinger_file_bridge/server.py src/hostinger_file_bridge/cli.py tests/test_legacy_adapter.py tests/test_server_tools.py
git commit -m "feat: expose v0.2 filesystem mcp and cli"
```

---

### Task 10: Ephemeral SSH/SFTP Integration Fixture and CI

**Files:**
- Create: `tests/integration/ssh_fixture/Dockerfile`
- Create: `tests/integration/ssh_fixture/sshd_config`
- Create: `tests/integration/test_ssh_sftp.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Integration fixture exposes SFTP + shell on a non-production port with known test credentials and a verified generated host key.
- Include both a normal path namespace test and a chroot-like SFTP namespace test.

- [ ] **Step 1: Write integration tests**

Test key auth, password-secret auth, host-key rejection, capability discovery, upload/download, SFTP fallback copy, shell accelerated copy/checksum, alias/home/absolute resolution, symlink non-following, archive roundtrip, and sync dry-run/execute.

- [ ] **Step 2: Build fixture and prove tests fail before fixture wiring**

Run:

```bash
docker build -t hfb-ssh-fixture tests/integration/ssh_fixture
pytest tests/integration -v
```

Expected: initial FAIL until fixture orchestration is complete.

- [ ] **Step 3: Wire CI integration job**

CI starts the fixture, waits for SSH readiness, writes a temporary known_hosts entry from the fixture’s pinned test host key, runs integration tests, and always tears down the container.

No Hostinger production credentials are used in CI.

- [ ] **Step 4: Run complete suite**

Run: `pytest -v`
Expected: PASS unit + integration tests locally with Docker available.

- [ ] **Step 5: Commit**

```bash
git add tests/integration .github/workflows/ci.yml
git commit -m "test: add ssh sftp integration fixture"
```

---

### Task 11: Documentation, Migration, Verification, and Release Metadata

**Files:**
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `docs/DEPLOY.md`
- Modify: `docs/CHATGPT_SETUP.md`
- Create: `docs/MIGRATION_v0.1_to_v0.2.md`
- Modify: `.env.example`
- Modify: `CHANGELOG.md`
- Replace: `VERIFICATION.json`

**Interfaces:**
- Documentation is the public contract for configuration, aliases, absolute mode, approvals, browser transfers, sync, archives, and legacy behavior.

- [ ] **Step 1: Rewrite README opening and quickstart**

Lead with:

> Hostinger File Bridge is an account-scoped SSH/SFTP filesystem bridge for ChatGPT, Codex, browser workflows, and CLI automation.

Show `home`, alias, and `absolute` examples. The old `gpt-export-rename` path appears only as an example alias.

- [ ] **Step 2: Document migration exactly**

Map each old environment variable/tool to the new connection/base/path equivalent and state that deprecated tool names remain for the v0.2 release cycle.

- [ ] **Step 3: Update security/deployment docs**

Document host-key enrollment, secrets, SFTP-vs-shell namespace mapping, audit log, approval fingerprints, URL allowlists, symlink policy, and single-process ticket-store limitation.

- [ ] **Step 4: Run verification commands and capture evidence**

Run:

```bash
python -m compileall -q src
pytest -v
python -m build
```

Update `VERIFICATION.json` with the actual command results, tested Python versions, date, commit SHA, and explicit `live_hostinger_test: not_run` unless a secret-gated dedicated test directory is intentionally configured.

- [ ] **Step 5: Update changelog and commit**

```bash
git add README.md SECURITY.md docs .env.example CHANGELOG.md VERIFICATION.json
git commit -m "docs: release account-scoped filesystem v0.2"
```

---

## Self-Review

### Spec coverage

- Full SSH-visible account: Tasks 1–5, 9.
- Aliases/home/absolute paths: Tasks 1–2, 9–11.
- SFTP/shell namespace distinction: Tasks 2–3, 10.
- Auth hierarchy/host-key verification: Tasks 1, 3, 10–11.
- Capability discovery: Task 3.
- SFTP baseline + shell acceleration: Tasks 5, 7–8.
- Compact MCP surface: Task 9.
- Risk levels/preflight/fingerprints: Task 4, consumed by Tasks 5–9.
- Bounded read/find: Tasks 1, 5, 9.
- Atomic writes/concurrency: Task 5.
- One-time browser tickets and SSRF controls: Task 6.
- Safe archives: Task 7.
- Sync/rsync fallback: Task 8.
- Audit persistence: Task 4.
- Symlink behavior: Tasks 2, 5, 7–8, 10.
- Legacy v0.1 adapter: Task 9.
- Integration fixture: Task 10.
- Documentation/release evidence: Task 11.

### Placeholder scan

No `TBD`, `TODO`, “implement later,” or undefined implementation placeholders are part of the plan. Live Hostinger testing is intentionally optional and explicitly gated by the approved spec.

### Type/interface consistency

`PathSpec`, `ResolvedPath`, `ConnectionCapabilities`, `OperationPlan`, `MutationResult`, and `AuditEvent` are introduced in Task 1 and consumed consistently by later tasks. Policy plans use `plan_id` + `fingerprint`; no later task uses a generic `confirm=true` shortcut for destructive execution.

## Execution handoff

Recommended execution: **Subagent-Driven Development**, one fresh implementation worker per task with review gates between tasks. Inline execution is also valid if the session keeps strict task checkpoints.
