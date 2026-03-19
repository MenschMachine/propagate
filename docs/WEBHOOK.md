# GitHub Webhook Listener

`propagate-webhook` is a lightweight HTTP server that receives GitHub webhook events and forwards them as propagate signals via ZeroMQ.

---

## Installation

```bash
pip install propagate[webhook]
```

---

## Usage

### Coordinator mode (recommended)

```bash
propagate-webhook --port 8080
```

Connects to the coordinator and forwards all GitHub events. The coordinator routes each signal to the correct worker(s) by matching the `repository` field in the payload against each project's configured repository URLs. A single webhook instance serves all projects.

No `--config` or `--project` flag is needed — signal validation is handled by the workers.

### Legacy mode

```bash
propagate-webhook --config config/propagate.yaml --port 8080
```

Connects directly to a config's ZMQ socket. The `--config` path must match the one used by `propagate serve`. Signals are validated against the config before sending.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | (none) | Path to a propagate YAML config (legacy mode). If omitted, connects to coordinator. |
| `--port` | `8080` | Port to listen on |
| `--host` | `0.0.0.0` | Host to bind to |
| `--secret` | (none) | GitHub webhook secret for HMAC-SHA256 verification |
| `--secret-env` | (none) | Environment variable name containing the webhook secret |
| `--debug` | off | Enable debug-level logging |

---

## Event Mapping

GitHub events are mapped to propagate signal names using the convention `{event}.{action}`:

| GitHub Event | Action | Signal Name |
|---|---|---|
| `pull_request` | `labeled` | `pull_request.labeled` |
| `pull_request` | `opened` | `pull_request.opened` |
| `pull_request` | `closed` | `pull_request.closed` |
| `issues` | `labeled` | `issues.labeled` |
| `issues` | `opened` | `issues.opened` |
| `issues` | `closed` | `issues.closed` |
| `issues` | `reopened` | `issues.reopened` |
| `issues` | `unlabeled` | `issues.unlabeled` |
| `push` | — | `push` |
| `issue_comment` | `created` | `issue_comment.created` |

Unsupported event types are ignored with a 200 response.

### Payload Fields

**pull_request.\*:**

| Field | Description |
|-------|-------------|
| `repository` | `owner/repo` |
| `pr_number` | Pull request number |
| `merged` | `true` if the PR is merged, else `false` |
| `action` | GitHub action (opened, labeled, etc.) |
| `label` | Label name (only for labeled/unlabeled) |
| `head_ref` | Source branch |
| `base_ref` | Target branch |
| `sender` | GitHub username |

**push:**

| Field | Description |
|-------|-------------|
| `repository` | `owner/repo` |
| `ref` | Git ref (e.g. `refs/heads/main`) |
| `head_commit_sha` | HEAD commit SHA |
| `sender` | GitHub username |

**issues.\*:**

| Field | Description |
|-------|-------------|
| `repository` | `owner/repo` |
| `issue_number` | Issue number |
| `issue_title` | Issue title |
| `issue_body` | Issue body |
| `state` | Issue state (`open`, `closed`) |
| `action` | GitHub action (`opened`, `labeled`, etc.) |
| `label` | Label name (only for `labeled` / `unlabeled`) |
| `sender` | GitHub username |

**issue_comment.created:**

| Field | Description |
|-------|-------------|
| `repository` | `owner/repo` |
| `issue_number` | Issue/PR number |
| `comment_body` | Comment text |
| `is_pull_request` | `true` if comment is on a PR |
| `sender` | GitHub username |

---

## Config Example

Define signals matching the GitHub event convention, then use them in propagation triggers:

```yaml
version: "6"
agent:
  command: "claude --prompt-file {prompt_file}"

repositories:
  app:
    path: ./

signals:
  pull_request.labeled:
    payload:
      repository:
        type: string
        required: true
      pr_number:
        type: number
        required: true
      label:
        type: string
        required: true
      head_ref:
        type: string
      base_ref:
        type: string
      sender:
        type: string
      action:
        type: string

executions:
  build:
    repository: app
    sub_tasks:
      - id: compile
        prompt: ./prompts/build.md

  deploy:
    repository: app
    sub_tasks:
      - id: ship
        prompt: ./prompts/deploy.md

propagation:
  triggers:
    - after: build
      run: deploy
      on_signal: pull_request.labeled
```

```bash
# Terminal 1: start propagate — runs build, then waits for the label event
propagate run --config config/propagate.yaml --execution build

# Terminal 2: start webhook listener
propagate-webhook --config config/propagate.yaml --port 8080 --secret-env GITHUB_WEBHOOK_SECRET
```

When a PR is labeled in GitHub, the webhook fires, the signal is delivered, and the `deploy` execution starts.

---

## Local Development with Smee.io

For local development, GitHub can't reach `localhost`. [Smee.io](https://smee.io) acts as a proxy: GitHub sends webhooks to a public Smee URL, and a local client forwards them to your `propagate-webhook` server.

### Prerequisites

- `npm` (for installing `smee-client`)
- `gh` CLI (authenticated — for creating/deleting webhooks)

### Setup

`propagate-setup.py` does the following:

1. Checks that `gh` is authenticated
2. Reads your propagate config and extracts every GitHub `owner/repo` (deduped) — for `url:` repos it parses the URL directly, for `path:` repos it reads the git origin remote
3. Creates a new Smee channel by hitting `https://smee.io/new` — or reuses the existing one if `.smee.json` already exists
4. For each repo not already in `.smee.json`, creates a GitHub webhook (via `gh api`) pointing at the Smee channel URL
5. Extracts all labels used in the config (from execution signal filters, routes, propagation triggers, `git:pr-labels-add` hooks, and prompt annotations like `<!-- propagate-required-labels: my-label -->`) and creates any missing ones on each repo
6. Writes `.smee.json` with the channel URL, port, secret, and webhook IDs for teardown

```bash
# 1. Create Smee channel, webhooks, and labels
scripts/propagate-setup.py --config config/propagate.yaml

# 2. Start the Smee forwarder (Terminal 1)
scripts/smee-start.sh

# 3. Start propagate-webhook (Terminal 2)
propagate-webhook --config config/propagate.yaml --port 8080
```

Options for `propagate-setup.py`:

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | (required) | Path to propagate YAML config |
| `--port` | `8080` | Port for the local webhook server (stored in `.smee.json` for `smee-start.sh`) |
| `--events` | `push,pull_request,issues,issue_comment` | Comma-separated GitHub event types to subscribe to |
| `--secret` | (random) | Webhook secret for HMAC verification. Auto-generated if omitted |
| `--skip-smee` | off | Skip smee webhook setup |
| `--skip-labels` | off | Skip label creation |
| `--dry-run` | off | Show what would be done without making changes |

### Teardown

```bash
scripts/smee-teardown.sh
```

This deletes the GitHub webhooks and removes `.smee.json`.

> **Note:** The secret is stored in `.smee.json`. Pass it to `propagate-webhook` via `--secret` if you want HMAC verification during local dev. Smee forwards the `X-Hub-Signature-256` header as-is, so verification works.

---

## GitHub Setup

1. Go to your repository's **Settings → Webhooks → Add webhook**
2. Set **Payload URL** to `http://your-server:8080/webhook`
3. Set **Content type** to `application/json`
4. Set a **Secret** and pass the same value via `--secret` or `--secret-env`
5. Select the events you need (Pull requests, Issues, Pushes, Issue comments)

---

## HMAC Verification

When `--secret` or `--secret-env` is provided, every request must include a valid `X-Hub-Signature-256` header. Requests with missing or invalid signatures are rejected with 403.

Without a secret, all requests are accepted. This is only suitable for development/testing.
