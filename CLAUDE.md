# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Propagate

A self-propagating task orchestration system that coordinates multi-stage agent workflows across Git repositories.
Executions form a DAG, each operating on a repository with sequential sub-tasks driven by agent commands. Supports
signals (typed events), propagation triggers, and a 3-tier context store.

## Commands

```bash
# Run all tests
./venv/bin/python -m pytest tests/ -v

# Run a single test file
./venv/bin/python -m pytest tests/test_stage6.py -v

# Run a single test
./venv/bin/python -m pytest tests/test_stage6.py::TestStage6::test_name -v

# Install locally (editable)
./venv/bin/pip install -e .

# Lint
./venv/bin/ruff check propagate_app/ tests/

# Lint with auto-fix
./venv/bin/ruff check --fix propagate_app/ tests/

# Run CLI
./venv/bin/propagate run --config config/propagate.yaml

# Run as long-lived server
./venv/bin/propagate serve --config config/propagate.yaml

# Clear all context and run state
./venv/bin/propagate clear --config config/propagate.yaml
```

## Architecture

Entry point: `propagate_app/cli.py` → `main()`

### Core Flow

1. **Config loading** (`config_load.py`): Parse YAML v6, validate DAG (no cycles via `graph.py`)
2. **Signal parsing** (`signals.py`): Match CLI signal args to config-defined signals with typed payloads
3. **Scheduler** (`scheduler.py`): Run execution DAG — activate initial + dependencies, loop picking next runnable, run,
   capture completion, activate propagation triggers
4. **Execution flow** (`execution_flow.py`): Route to git-managed or direct sub-task path
5. **Sub-tasks** (`sub_tasks.py`): Sequential agent tasks with before/after/on_failure hooks, prompt templating, agent
   command invocation

### Key Abstractions

- **Executions**: Named tasks operating on a repository, composed of sub-tasks
- **Context Store** (`context_store.py`): 3-tier key-value store — global, execution-scoped, task-scoped. Root defaults
  to `.propagate-context/`
- **Signals**: Typed event triggers with payloads that activate executions
- **Propagation Triggers**: DAG edges (`after: X, run: Y, on_signal: Z`)
- **Run State** (`run_state.py`): Persisted to `.propagate-state-{name}.yaml` for resume support

### Git Integration

`git_operations.py`, `git_pr.py`: Auto branch creation, commit, push, PR creation per execution when git config is
present.

### Environment Variables

- `PROPAGATE_CONTEXT_ROOT`: Context store root directory
- `PROPAGATE_EXECUTION`: Current execution name (set during runs)
- `PROPAGATE_TASK`: Current task ID (set during runs)

## Config Format

YAML with `version: "6"` required. Key sections: `agent`, `repositories`, `context_sources`, `signals`, `executions`,
`propagation`. See `docs/CONFIG_REFERENCE.md` for full spec.

## Conventions

- Logger: `from propagate_app.constants import LOGGER` — use `LOGGER.debug()` for debug output
- Errors: raise `PropagateError` from `propagate_app.errors`
- Models are dataclasses in `models.py`
- Context keys must match: `^:?[A-Za-z0-9][A-Za-z0-9._-]*$`
- Config parsing is split across `config_agent.py`, `config_git.py`, `config_signals.py`, `config_executions.py`

## Developer Guidelines

- Always write failing tests first
- One test file per feature or bugfix
- keep everything under docs/ always up to date. Check if your changes need to be reflected there.
- Write tests using pytest style (plain functions + fixtures), not `unittest.TestCase` classes
- Always keep docs up to date, especially the feature related docs like GIT.md, SIGNAL.md. If one is missing for your
  feature or subsystem, create it.
- If there are changes in config syntax, features, etc. update CONFIG_REFERENCE.mdg