# Bootstrapping Propagate

Propagate should develop itself. The same way a self-hosting compiler is written in the language it compiles, Propagate's own development should be orchestrated by Propagate.

## Why

If the tool can't handle its own development workflow, it's not good enough. Bootstrapping is the ultimate integration test — every rough edge in the config format, every gap in the context model, every missing feature surfaces immediately because you're living inside the system.

It also means the config, prompts, and guidelines for Propagate's own repo become a maintained, real-world reference that evolves alongside the tool.

## The cold start

The very first version can't be written by Propagate because Propagate doesn't exist yet. Every self-hosting compiler has a hand-written first version. But the hand-written part should be as small as possible.

The config files live inside the repo the agent operates on. This is not circular — the config is read at execution start. Changes the agent makes to config files take effect on the *next* run, not the current one.

## Self-propagating stages

Each stage is produced by the previous stage. Each stage adds exactly one meaningful capability and removes one manual step.

Crucially, each stage doesn't just produce the *code* for the next stage — it also produces the **config and prompt files** that the next stage needs to build the stage after it. The output of every stage is:

1. The next stage's runtime (code)
2. The next stage's `propagate.yaml` (or equivalent config)
3. The next stage's prompt files

This means stage 0's bootstrapping prompt must describe not just "build me a CLI" but also "produce the config and prompts that your CLI will use to build stage 2." Each stage seeds the next one with everything it needs to continue the chain.

Earlier stages have less capability, so their configs and prompts are simpler. Stage 1 has no context bag, so the stage 2 prompts must carry context inline. Stage 2 has a context bag, so the stage 3 prompts can be leaner. Stage 3 has hooks, so the stage 4 config can use them. The configs get richer as the tool gets richer.

### Stage 0: The script

Using the protype pdfdancer-propagate for that.

The prompt contains everything inline — the full Propagate design spec, the task description. There is no external context, no config, no structure. It's a dumb pipe: file in, agent, files out.

Stage 0's job is to produce stage 1. The bootstrapping prompt asks the agent to build the first real `propagate` CLI — and to produce the config and prompts that stage 1 will use to build stage 2.

**Produces:**
- `propagate` CLI (stage 1 runtime — config parsing, sub-task sequencing, agent call)
- `config/propagate.yaml` (stage 1 config — one execution with sub-tasks for building stage 2)
- `config/prompts/stage2-*.md` (prompts that describe the context bag, with all context inline since stage 1 has no context bag)

**Removes:** nothing (this is the hand-written seed)

### Stage 1: Config-driven execution

`propagate --config config.yaml`

Reads a YAML config file, finds the execution, finds the sub-tasks in order, reads each sub-task's prompt file, passes each one to the configured agent command sequentially.

The prompt files still carry all context inline — you hand-write them with whatever the agent needs to know. But the structure is now config-driven. Multiple sub-tasks run in sequence. You can have design → implement → review as three separate prompts that execute one after another.

No context bag, no hooks, no git, no signals.

**Produces:**
- Updated `propagate` CLI (stage 2 runtime — adds context bag and `propagate context set/get`)
- Updated `config/propagate.yaml` (stage 2 config — uses context bag for the first time)
- `config/prompts/stage3-*.md` (prompts that describe hooks and context sources — still carry context inline since stage 2 has no hooks to load it automatically)

**Removes:** hardcoded paths, single-shot execution.

### Stage 2: Context bag

`propagate context set key value` and `propagate context get key` work.

The context bag is a key-value store. The runtime passes all context values to the agent alongside the prompt. Prompt files become reusable templates that work with different context values — you stop editing prompts per-task.

Values are populated manually before running `propagate --config`. No hooks yet, so there's no way to automate context loading. You run `propagate context set` yourself, then run the execution.

No hooks, no git, no signals.

**Produces:**
- Updated `propagate` CLI (stage 3 runtime — adds hooks, `on_failure`, context source `:name` loading)
- Updated `config/propagate.yaml` (stage 3 config — uses hooks to load context sources and validate output)
- `config/context-sources.yaml` (first context sources — can now exist because stage 3 has hooks to load them)
- `config/prompts/stage4-*.md` (prompts are now leaner — hooks handle context loading, prompts focus on the task)

**Removes:** pasting context into prompt files.

### Stage 3: Hooks and context sources

Sub-tasks support `before`, `after`, and `on_failure` hooks — shell commands that run around the agent call.

This is where `propagate context set :openapi-spec` starts working. Hooks load context sources automatically, run validation (tests, linting), manage labels via `gh pr edit`. The `after` hook failing means the sub-task failed.

The runtime is now: for each sub-task, run before hook → call agent → run after hook. With context flowing through the bag.

No git, no signals.

**Produces:**
- Updated `propagate` CLI (stage 4 runtime — adds git operations, branch/commit/push/PR)
- Updated `config/propagate.yaml` (stage 4 config — includes `git:` block with branch prefix and message source)
- Updated prompts for stage 5 (git is now automatic, prompts no longer mention manual commit steps)

**Removes:** manually populating context, manually validating output.

### Stage 4: Git operations

Commit + push after each sub-task. Branch creation from PR title with configurable prefix. PR creation for new work. Commit message generated by a context source (`message_source`).

The core rule: if the execution already has a PR (because one triggered it), work on that PR's branch. If it doesn't, create a new branch and open a PR after the first push.

`on_failure` hooks become meaningful — if the after hook fails, the commit doesn't happen, and the failure hook runs.

No signals — you still trigger runs manually.

**Produces:**
- Updated `propagate` CLI (stage 5 runtime — adds signal detection, propagation block, `wait_for`)
- Updated `config/propagate.yaml` (stage 5 config — includes `propagation:` block with signal triggers)
- Updated prompts for stage 6 (can now assume autonomous triggering)

**Removes:** manually committing and pushing.

### Stage 5: Signals and the propagation block

PR events trigger executions automatically. The `propagation` block is read. Labels, merges, and PR creation are watched.

`wait_for` gates on sub-tasks work — the execution pauses until a signal fires (like `design_approved` label added by a human).

Propagate now runs autonomously on a single repo. A PR with the right label triggers the right execution. This is where Propagate starts developing itself.

**Removes:** manually triggering runs.

### Stage 6: Multi-repo and propagation DAG

Fan-out, fan-in, upstream/downstream context. The full `propagation` block with `tasks_completed` signals. The `--task` scope on `propagate context get` works.

Cross-repo orchestration. A merged PR in one repo triggers SDK updates across three languages, which fan-in to trigger docs and integration tests.

Global context (`--global`) for values shared across the entire propagation run.

**Produces:**
- The final `propagate` CLI (feature complete)
- The final `config/` directory (the real, maintained Propagate-for-Propagate config)
- The final prompts and guidelines (the living reference that evolves with the tool)

**Removes:** single-repo limitation. Feature complete.

## Summary

| Stage | Produced by | Adds | Output includes | Removes (manual step) |
|-------|-------------|------|----------------|-----------------------|
| 0 | Hand-written | Script: prompt → LLM → files | Stage 1 code + config + prompts | — |
| 1 | Stage 0 | Config parsing, sub-task sequencing | Stage 2 code + config + prompts (context inline) | Hardcoded paths, single-shot |
| 2 | Stage 1 | Context bag | Stage 3 code + config + prompts (context via bag) | Pasting context into prompts |
| 3 | Stage 2 | Hooks, context sources | Stage 4 code + config + context-sources.yaml | Manually loading context, manually validating |
| 4 | Stage 3 | Git operations | Stage 5 code + config with git block | Manually committing and pushing |
| 5 | Stage 4 | Signals, wait_for, propagation triggers | Stage 6 code + config with propagation block | Manually triggering runs |
| 6 | Stage 5 | Multi-repo, DAG, global context | Final runtime + final config (self-maintaining) | Single-repo limitation |

## What makes this interesting

The prompts and guidelines for Propagate's own development are *about* Propagate. The agent needs to understand the tool it's building in order to build it well. This creates a tight feedback loop:

- The guidelines describe how Propagate's config format works.
- The agent uses that knowledge to implement changes to the config format.
- If the guidelines are wrong or incomplete, the agent produces bad output.
- That forces the guidelines to improve.

The context sources are self-referential. A context source might run `propagate --version` or inspect the config schema. The agent uses Propagate's own CLI to understand the current state of the tool it's modifying.

Starting at stage 5, Propagate handles its own PRs. From that point forward, every new feature — including stages 5 and 6 themselves — can be proposed as a PR and processed by the tool.
