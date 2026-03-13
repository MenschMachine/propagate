# Feature Gap Analysis

Features available in pdfdancer-propagate but not in propagate.

## Webhook & Event System
- **GitHub webhook server** — HTTP daemon that listens for PR events, verifies HMAC signatures, routes events
- **Smee.io integration** — local dev webhook routing
- **Event-driven triggering** — watches for PR labels to auto-start propagations (vs CLI-only here)
- **Capability file detection** — auto-extracts capability key from files added in PRs

## Review Workflows
- **Agent review mode** — agent automatically reviews PRs, flags issues
- **Human review mode** — PR sits in `review_pending` for human approval
- **Combined review** — agent reviews first, then human approval required
- **Review resumption** — resumes via GitHub PR review actions or labels

## CI Integration
- **CI monitoring** — waits for `check_suite` completion webhooks
- **Auto-fix on CI failure** — re-runs agent with failure details (check run summaries + annotations)
- **Configurable retry limit** (`maxCiRetries`) with failure escalation

## Fan-In (Multi-Source) Edges
- **Multi-source dependencies** — waits for ALL source repos to complete before cascading to a target
- **Deduplication** — prevents running the same fan-in edge twice

## Auto-Propagation Chaining
- **`autoPropagate`** — automatically labels target PR with a trigger label when done, cascading through the graph without manual intervention

## Lifecycle Hooks (6 points)
- `on-propagation`, `before-agent`, `after-agent`, `before-review`, `after-review`, `after-propagation`
- All with variable interpolation; can be single command or array

## Template System
- **Shell command templates** — prefix with `$` to execute a command and use stdout as the value
- **Variable interpolation** in branch names, commit messages, PR title/body (`{capability}`, `{org}`, `{repo}`, `{number}`, `{prUrl}`, etc.)

## Dashboard & API
- **Web dashboard** — real-time status visualization with filtering, auto-refresh, auth
- **REST API** — query propagations, pause/resume/retry individual targets, stream logs, trigger reconciliation

## State Management & Recovery
- **Persistent state machine** — fine-grained per-target status (`pending`, `running`, `ci_pending`, `ci_fixing`, `review_pending`, `paused`, `done`, `failed`, etc.)
- **Phase-aware resumption** — restarts from the exact failed phase (agent, doc-agent, pushing, pr-create)
- **Reconciliation loops** — on startup and periodic polling to recover stuck/incomplete propagations
- **Pause/resume** — individual targets can be paused and resumed via API

## Agent Features
- **Doc agent** — separate agent for adding implementation notes to capability files
- **Review agent** — separate agent for code review
- **Global prompt** — markdown file prepended to every agent invocation
- **Agent timeout** — configurable kill after N seconds
- **Process registry** — tracks spawned agent processes, can kill on timeout
- **Agent stdout capture** — saved to `.last-message.txt`, templatable into PR body

## Shared Context
- **`.propagate-context.md`** — flows between phases and survives retries; agents can append data (versions, endpoints) for downstream phases to consume

## Parallel Execution
- **`parallel: true`** on edges — concurrent target execution with `Promise.allSettled()`

## Logging
- **Per-target log files** — `logs/{capability}--{repo}--{timestamp}.log`
- **Event log** — all GitHub events logged
- **Log streaming** — real-time via event emitter to dashboard

## Multi-Label Propagation
- **Multiple independent workflows** per trigger label — e.g., `propagate` label triggers feature work, `deployed` label triggers deployment propagation, each with its own edge graph

---

**Summary**: pdfdancer-propagate is a full daemon with webhook-driven automation, CI integration, review workflows, a dashboard, state recovery, and multi-agent orchestration. Propagate is a CLI-driven orchestrator focused on config-defined DAG execution. The biggest gaps are the event-driven server, CI/review loops, persistent state machine with recovery, and the monitoring UI.
