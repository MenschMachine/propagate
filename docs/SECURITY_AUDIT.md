# Security Audit — Propagate

**Date:** 2026-03-14

## CRITICAL

### 1. `shell=True` throughout command execution
**`propagate_app/processes.py:45-47`**

All user-facing command execution goes through `run_shell_command()` which uses `shell=True`. This is the single biggest attack surface. It's called from:

- **Hook actions** (`sub_tasks.py:174`) — `before`/`after`/`on_failure` config values executed as raw shell
- **Context source commands** (`context_sources.py:43`) — `context_sources.<name>.command` from YAML
- **Agent commands** (`processes.py:12-13`) — `agent.command` config value
- **Signal check commands** (`signal_reconcile.py:95`) — `check` templates with `shell=True`

All of these take strings from YAML config and pass them directly to a shell. The `# noqa: S602` comments show this is known and suppressed.

**Nuance:** This is somewhat by design — the tool orchestrates shell commands. But there's no validation, sandboxing, or allowlisting. A compromised or malicious config file = full RCE.

### 2. Unauthenticated ZeroMQ IPC socket
**`propagate_app/signal_transport.py:12-22`**

The signal socket lives at `ipc:///tmp/propagate-{hash}.sock` with:
- No authentication or encryption
- Predictable path (SHA256 of config path)
- World-accessible `/tmp` directory

Any local user who knows (or guesses) the config path can send arbitrary signals, triggering executions and shell commands.

### 3. Webhook runs without HMAC by default
**`propagate_webhook/server.py:47-48`**

The `--secret` flag is optional. Without it, the webhook accepts POST requests from anyone. Combined with default binding to `0.0.0.0` (`cli.py:18`), this exposes signal injection to the entire network.

---

## HIGH

### 4. Webhook binds `0.0.0.0` by default
**`propagate_webhook/cli.py:18`**

Default host is `0.0.0.0`, exposing the endpoint on all interfaces. Should default to `127.0.0.1`.

### 5. Full environment inherited by subprocesses
**`propagate_app/processes.py:41-43`**

```python
env = {**os.environ, **extra_env}
```

All env vars (`GITHUB_TOKEN`, `AWS_*`, etc.) are passed to every subprocess including agent commands. No allowlist filtering.

### 6. Git stderr leaked in error messages
**`propagate_app/repo_clone.py:27,40`**

Git stderr (which can contain auth failures, token fragments, private paths) is included directly in `PropagateError` messages that get logged.

---

## MEDIUM

### 7. Symlink following in context operations
**`propagate_app/sub_tasks.py:61`**

`evaluate_when_condition()` uses `Path.is_file()` and `Path.read_text()` which follow symlinks. An attacker with write access to the context directory could symlink a context key to read arbitrary files.

### 8. Context values stored as plaintext
**`propagate_app/context_store.py:157-178`**

All context values written to `.propagate-context-{name}/` as unencrypted files with default permissions. If context contains tokens or secrets, they're exposed at rest.

### 9. No rate limiting on any endpoint
Webhook, Telegram bot, and ZMQ serve loop all accept unlimited requests. Signal queue grows unbounded in memory.

### 10. TOCTOU in context reads
**`propagate_app/context_store.py:181-186`**

Existence check then read — file could be swapped between operations.

### 11. Debug logging of sensitive data
- **`propagate_webhook/server.py:65`** — Full webhook payloads logged at DEBUG level.
- **`propagate_app/signal_reconcile.py:93`** — Shell commands logged before execution.

No log redaction for secret patterns.

---

## LOW / INFORMATIONAL

### 12. No repo URL validation
**`propagate_app/repo_clone.py:19-20`** — Git URLs from config passed directly to `git clone` without format validation.

### 13. Temp file cleanup relies on manual `delete=False` pattern
**`propagate_app/temp_files.py:8-20`** — Orphaned temp files possible on crashes, though `try/finally` cleanup exists.

### 14. No TLS for ZeroMQ IPC
Signal payloads transmitted unencrypted between webhook/telegram and serve process.

---

## What's Done Well

- **YAML**: `yaml.safe_load()` used everywhere — no deserialization attacks
- **No `eval`/`exec`/`pickle`** anywhere in the codebase
- **Context key validation**: regex `^:?[A-Za-z0-9][A-Za-z0-9._-]*$` prevents path traversal via keys
- **Git commands**: use list args (no `shell=True`) in `git_repo.py`
- **HMAC verification**: timing-safe `hmac.compare_digest()` when enabled
- **Telegram auth**: user ID allowlist enforced before any action
- **Atomic file writes**: tempfile + `os.replace()` for context values
- **Signal payload validation**: strict type checking against config schema
- **Dependencies**: all at current versions, no known CVEs

---

## Recommendations (priority order)

1. **Make webhook secret mandatory** or at least warn loudly at startup when running without one
2. **Default webhook bind to `127.0.0.1`** instead of `0.0.0.0`
3. **Add ZMQ authentication** (ZeroMQ has CurveZMQ for this) or move socket to a user-private directory (`$XDG_RUNTIME_DIR`)
4. **Filter subprocess environment** — allowlist only needed vars instead of passing everything
5. **Redact secrets in logs** — filter patterns like tokens, keys before logging stderr or payloads
6. **Add symlink checks** before reading context files
7. **Document the trust model** — make explicit that config files are fully trusted and equivalent to code execution
