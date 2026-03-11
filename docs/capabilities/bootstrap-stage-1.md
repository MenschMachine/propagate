# Bootstrapping Propagate — Stage 0 Prompt

You are building Propagate, a CLI tool that orchestrates AI agent tasks across repositories. This is the bootstrapping prompt — the very first step in a self-hosting build chain where each stage produces the next.

## What is Propagate

Propagate reads a YAML config that defines executions (agent tasks) with sub-tasks. Each sub-task has a prompt file that gets sent to a configurable agent command. Propagate is LLM-agnostic — it's a pure orchestrator. The agent integration is just a shell command specified in config. In its full form, Propagate supports a context bag, hooks, git operations, signal-based triggering, and cross-repo orchestration. But we're building it in stages, and you're building stage 1 — the simplest possible version.

## The bootstrapping chain

Each stage produces the code for the next stage, plus the config and prompts that the next stage uses to build the stage after it.

| Stage | What it adds |
|-------|-------------|
| 0 | Hand-written script (this prompt) |
| 1 | Config parsing, sub-task sequencing, agent call |
| 2 | Context bag (`propagate context set/get`) |
| 3 | Hooks (before/after/on_failure shell commands around agent calls) |
| 4 | Git operations (commit, push, branch, PR) |
| 5 | Signals and propagation (PR events trigger executions) |
| 6 | Multi-repo and DAG orchestration |

You are producing stage 1. Stage 1 will then be used to produce stage 2.

## Your task: build stage 1

Write a Python CLI tool called `propagate` that does the following:

### What stage 1 does

1. Accepts `propagate run --config <path>` (or `propagate run --config <path> --execution <name>` to run a specific execution)
2. Parses a YAML config file
3. Finds the execution (if only one exists, use it; if multiple, require `--execution`)
4. Reads the sub-tasks in order
5. For each sub-task: reads the prompt file, passes it to the configured agent command
6. Runs sub-tasks sequentially — the output of one is visible to the next (they operate on the same working directory)

### What stage 1 does NOT do

- No context bag — prompts carry all context inline
- No hooks — no shell commands before/after agent calls
- No git operations — no commit, push, branch, or PR management
- No signals — no watching for PR events, no automatic triggering
- No propagation — no cross-repo orchestration
- No `includes` — single config file only
- No `defaults` — each execution is fully self-contained
- No guidelines — prompt files contain everything

### Config format for stage 1

The minimal config that stage 1 understands:

```yaml
version: "1"

agent:
  command: codex exec --dangerously-bypass-approvals-and-sandbox "Read the file {prompt_file} in this directory and follow its instructions."

executions:
  build-stage2:
    sub_tasks:
      - id: design
        prompt: ./prompts/design.md
      - id: implementation
        prompt: ./prompts/implement.md
      - id: review
        prompt: ./prompts/review.md
```

That's it. `version`, `agent`, `executions`, and within each execution: `sub_tasks` with `id` and `prompt`. Nothing else.

### Agent integration

Propagate is LLM-agnostic. The agent is a shell command configured in the YAML:

```yaml
agent:
  command: codex exec --dangerously-bypass-approvals-and-sandbox "Read the file {prompt_file} in this directory and follow its instructions."
```

Propagate writes the prompt to a temporary file, replaces `{prompt_file}` in the command with the path, and runs it. The agent command is responsible for reading the prompt and modifying files in the working directory. Propagate doesn't know or care what LLM the command uses.

The working directory is wherever `propagate run` is invoked from. The agent command inherits it.

If no `agent` block is in the config, Propagate should error with a clear message.

### CLI structure

```
propagate run --config <path> [--execution <name>]
```

Use `argparse` or `click`. Keep dependencies minimal: `pyyaml` and standard library. No LLM SDK needed — the agent is a subprocess.

### Code structure

Write this as a single Python file: `propagate.py`. It should be runnable as `python propagate.py run --config config.yaml`. Keep it simple — no package structure, no setup.py, no tests yet. Those come in later stages.

## Also produce: config and prompts for stage 2

Stage 1's purpose is to build stage 2. So in addition to the `propagate.py` code, also produce:

1. `config/propagate.yaml` — a stage 1 config that, when run with your CLI, will produce stage 2
2. `config/prompts/design-stage2.md` — a prompt for the design sub-task
3. `config/prompts/implement-stage2.md` — a prompt for the implementation sub-task
4. `config/prompts/review-stage2.md` — a prompt for the review sub-task

### What stage 2 adds

Stage 2 adds the context bag to `propagate.py`. Specifically:

- `propagate context set <key> <value>` — writes a key-value pair to a local store
- `propagate context get <key>` — reads a value
- The context bag is a directory of files (`.propagate-context/<key>` contains the value)
- When running `propagate run`, all context values are appended to the prompt file contents as a "Context" section before passing it to the agent command
- The agent sees all context values automatically — they're part of the prompt it receives
- No `--task` or `--global` scoping yet — that comes in stage 6

The stage 2 prompts must carry all context inline (since stage 1 has no context bag). This means each prompt must contain:

- The full Propagate design vision (what the tool will eventually become)
- The current state of `propagate.py` (stage 1 code — the agent will be modifying this file)
- The specific task for that sub-task (design the context bag, implement it, review the implementation)

Since stage 1 prompts must be self-contained, the design prompt should describe the context bag in detail: how it's stored, how the CLI subcommands work, how values are injected into the agent prompt, and how this connects to the larger vision (hooks in stage 3 will use the context bag to load context sources via `propagate context set :source-name`).

## The full vision (for reference)

The complete Propagate config format — what stage 6 looks like — is summarized below. You don't need to implement any of this now, but the stage 2 prompts should reference this vision so the chain continues:

**Config sections:** version, includes, defaults, repositories, context_sources, executions, propagation

**Context:** A key-value bag with three scopes (local, task, global). Auto-populated from trigger signals (pr_number, pr_title, etc.). Written by hooks via `propagate context set`. The agent sees all global + local context automatically. Context sources are named shell commands loaded via `propagate context set :name`.

**Executions:** Task definitions with sub-tasks. Each sub-task has a prompt, optional hooks (before/after/on_failure), and optional `wait_for` gates. Guidelines are markdown files listed on the execution.

**Hooks:** Shell commands that run around agent calls. Used for: loading context sources, running tests, managing PR labels via `gh pr edit`, validation.

**Git:** Commit + push after every sub-task. Branch creation from PR title. PR creation for downstream work. Commit message from a context source.

**Propagation:** DAG wiring — signals trigger executions. Fan-out (one trigger → multiple tasks), fan-in (multiple tasks must complete → next task). Signal types: pr_closed_merged, pr_label_changed, pr_created, manual, tasks_completed, task_failed.

## Output

Produce these files:

```
propagate.py                        # The stage 1 CLI
config/propagate.yaml               # Config for building stage 2
config/prompts/design-stage2.md     # Design prompt for stage 2
config/prompts/implement-stage2.md  # Implementation prompt for stage 2
config/prompts/review-stage2.md     # Review prompt for stage 2
```

## Implementation in propagate

This repo implements stage 1 in a single-file runtime at `propagate.py`. The CLI exposes `propagate run --config <path> [--execution <name>]` via `argparse`, parses YAML with `PyYAML`, validates the minimal stage 1 schema, resolves prompt paths relative to the config file, and runs sub-tasks sequentially in the current working directory so each agent step sees the filesystem changes from the previous one.

Agent execution is configured entirely through `agent.command` in `config/propagate.yaml`. For each sub-task, `propagate.py` reads the prompt file, writes it to a temporary markdown file, substitutes `{prompt_file}` into the configured shell command, executes that command with `subprocess.run(..., shell=True, check=True)`, and then removes the temporary file. Repo-specific error handling is implemented with a `PropagateError` exception plus structured logging instead of `print()`.

The stage 1 bootstrap chain is also checked into this repo: `config/propagate.yaml` defines a single `build-stage2` execution, and `config/prompts/design-stage2.md`, `config/prompts/implement-stage2.md`, and `config/prompts/review-stage2.md` seed the next stage with the full inline context needed to add the context bag. External dependencies stay minimal; `requirements.txt` pins `PyYAML>=6.0,<7.0`.
