# GitHub Webhook Listener

`propagate-webhook` is a lightweight HTTP server that receives GitHub webhook events and forwards them as propagate signals via ZeroMQ.

---

## Installation

```bash
pip install propagate[webhook]
```

---

## Usage

```bash
propagate-webhook --config config/propagate.yaml --port 8080
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | (required) | Path to the propagate YAML config |
| `--port` | `8080` | Port to listen on |
| `--host` | `0.0.0.0` | Host to bind to |
| `--secret` | (none) | GitHub webhook secret for HMAC-SHA256 verification |
| `--secret-env` | (none) | Environment variable name containing the webhook secret |

The `--config` path must match the one used by `propagate run` — it determines the ZeroMQ socket address.

---

## Event Mapping

GitHub events are mapped to propagate signal names using the convention `{event}.{action}`:

| GitHub Event | Action | Signal Name |
|---|---|---|
| `pull_request` | `labeled` | `pull_request.labeled` |
| `pull_request` | `opened` | `pull_request.opened` |
| `pull_request` | `closed` | `pull_request.closed` |
| `push` | — | `push` |
| `issue_comment` | `created` | `issue_comment.created` |

Unsupported event types are ignored with a 200 response.

### Payload Fields

**pull_request.\*:**

| Field | Description |
|-------|-------------|
| `repository` | `owner/repo` |
| `pr_number` | Pull request number |
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

## GitHub Setup

1. Go to your repository's **Settings → Webhooks → Add webhook**
2. Set **Payload URL** to `http://your-server:8080/webhook`
3. Set **Content type** to `application/json`
4. Set a **Secret** and pass the same value via `--secret` or `--secret-env`
5. Select the events you need (Pull requests, Pushes, Issue comments)

---

## HMAC Verification

When `--secret` or `--secret-env` is provided, every request must include a valid `X-Hub-Signature-256` header. Requests with missing or invalid signatures are rejected with 403.

Without a secret, all requests are accepted. This is only suitable for development/testing.
