# Multi-Repo And DAG Stage 6 Design

## Scope

Stage 6 is the final runtime extension for Propagate. It adds:

- config-defined local repositories
- per-execution repository routing
- explicit execution dependencies
- deterministic DAG scheduling across repositories
- stage-5 signal and propagation-trigger compatibility inside the DAG model

Stage 6 keeps the current runtime model intact wherever possible:

- the implementation stays in `propagate.py`
- each execution still runs one sub-task at a time
- hooks, context sources, prompt augmentation, and git automation keep their existing meaning
- all work still happens through local subprocesses
- there is still no parallelism, retry loop, background worker, or stage 7 target

Stage 6 also preserves existing repository-local behavior:

- an execution without a repository binding still runs in `Path.cwd()`
- `.propagate-context` stays file-backed and local to the execution working directory
- `propagate context set/get` keep their current CLI shape and still operate on `Path.cwd()`

## Config Shape

Bump the schema marker to `version: "6"` and require that exact value in `load_config()`.

Add one optional top-level section and two optional execution fields:

```yaml
version: "6"

repositories:
  core:
    path: .
  docs:
    path: ../docs-site

signals:
  repo-change:
    payload:
      branch:
        type: string
        required: true

executions:
  build-core:
    repository: core
    signals:
      - repo-change
    sub_tasks:
      - id: build
        prompt: ./prompts/build-core.md

  update-docs:
    repository: docs
    depends_on:
      - build-core
    sub_tasks:
      - id: docs
        prompt: ./prompts/update-docs.md

propagation:
  triggers:
    - after: build-core
      on_signal: repo-change
      run: update-docs
```

Validation rules:

- `repositories` is optional. If present, it must be a non-empty mapping.
- Each repository name must validate with the same rules used for context-source names.
- Each repository definition is a mapping with exactly one required field in stage 6: `path`.
- `repositories.<name>.path` must be a non-empty string.
- Repository paths resolve relative to the config file, not `Path.cwd()`.
- `executions.<name>.repository` is optional. If present, it must reference a defined repository.
- `executions.<name>.depends_on` is optional. If present, it must be a non-empty list of unique execution names.
- `depends_on` entries must not reference unknown executions or the execution itself.
- Stage-5 `signals`, `git`, `sub_tasks`, and `propagation.triggers` keep their current schema.

Stage 6 does not add repository URLs, cloning, fetching, per-repository defaults, global context, or task-scoped context.

## Repository Definitions

Repositories are local working-directory aliases, not remote checkout instructions.

Recommended parsing shape:

```python
@dataclass(frozen=True)
class RepositoryConfig:
    name: str
    path: Path
```

Repository semantics:

- `path` may be absolute or relative.
- Relative paths resolve from `config_path.parent`.
- Store the resolved absolute path in `Config`.
- Do not normalize repository identity down to realpath-based deduplication. If two repository names point to the same path, allow it and treat that as intentional configuration.

This keeps the feature narrowly focused on routing existing local-process behavior into the right checkout.

## Execution-To-Repository Routing

Add two fields to `ExecutionConfig`:

```python
@dataclass(frozen=True)
class ExecutionConfig:
    name: str
    repository: str | None
    depends_on: list[str]
    signals: list[str]
    sub_tasks: list[SubTaskConfig]
    git: GitConfig | None
```

Working-directory resolution rules:

- If `execution.repository` is absent, use `Path.cwd()`. This preserves the stage-5 single-repo path unchanged.
- If `execution.repository` is present, resolve the working directory from `config.repositories[execution.repository].path`.
- Prompt files still resolve relative to the config file during config parsing.
- Everything that currently uses `runtime_context.working_dir` must use the execution-specific working directory instead:
  - `before` / `after` / `on_failure` hooks
  - context-source commands
  - prompt-context loading from `.propagate-context`
  - agent subprocess execution
  - git branch / commit / push / PR steps

Do not add per-sub-task or per-context-source working-directory overrides in stage 6. Repository routing is execution-scoped.

## Dependency Edges

`depends_on` defines hard prerequisites between executions.

Interpretation:

- `execution B depends_on [A]` means `A` must complete successfully before `B` may run.
- Dependencies may cross repository boundaries.
- Dependencies do not imply trigger behavior. They only constrain order once an execution has been activated for the current run.

When an execution becomes active, stage 6 must also activate its full dependency closure. This matters in two cases:

- the initial execution selected by `--execution` or signal auto-selection
- a follow-on execution activated later by a propagation trigger

This preserves a simple rule: if Propagate intends to run an execution, it must first intend to run everything that execution depends on.

## Deterministic DAG Scheduling

Stage 5 used a FIFO queue over execution names. Stage 6 replaces that with a deterministic DAG scheduler.

The scheduler still runs exactly one execution at a time.

### Graph model

Use one directed graph over executions with two edge types:

1. Dependency edges from each `depends_on` entry, oriented from prerequisite to dependent.
2. Propagation edges from `propagation.triggers`, oriented from `after` to `run`.

Cycle detection must use the combined graph, not just `depends_on`. Stage 6 is a DAG runtime, so any potential cycle is a configuration error.

For simplicity, cycle detection should ignore `trigger.on_signal` filtering and operate on the superset of all configured trigger edges. This may reject a config that would be acyclic for some signals, but it keeps the model predictable and implementation-ready.

### Activation model

The runtime tracks three sets:

- `active`: executions that are part of the current run plan
- `completed`: executions that have finished successfully
- `failed`: at most one execution, because the run stops on first failure

Initialization:

1. Resolve the active signal exactly as in stage 5.
2. Select the initial execution exactly as in stage 5.
3. Activate that execution and its dependency closure.

After each successful execution:

1. Evaluate propagation triggers in config order.
2. For each matching trigger, activate the target execution and its dependency closure.
3. Recompute the runnable set.

An execution is runnable when:

- it is active
- it is not completed
- all of its `depends_on` executions are completed

### Selection order

When multiple active executions are runnable at the same time, choose the first one in config declaration order.

That tie-breaker must be explicit and stable. Do not rely on incidental queue timing or subprocess completion, because stage 6 still runs sequentially.

One straightforward implementation is:

1. Record `execution_order = list(config.executions)`.
2. On each scheduler iteration, scan `execution_order`.
3. Run the first execution whose name is active, incomplete, and dependency-satisfied.

This yields a deterministic topological schedule without introducing a second ordering system.

### Completion condition

The run succeeds when every active execution completes successfully and no further triggers activate new executions.

The run fails immediately on the first execution failure. Stage 6 does not continue with other runnable nodes after a failure.

## Signals And Propagation Triggers

Stage-5 signal behavior stays narrow.

Signal rules that remain unchanged:

- `--signal`, `--signal-payload`, and `--signal-file` keep their current behavior.
- `executions.<name>.signals` still controls signal-based initial execution selection.
- `propagation.triggers[].on_signal` still filters whether a trigger fires after success.
- Trigger evaluation still happens only after a fully successful execution, including any configured git automation.

Stage-6 interaction rules:

- `signals` continues to matter only for direct execution selection, not for downstream dependencies or triggered executions.
- A dependency may run even if it does not list the active signal.
- A triggered execution may run even if it does not list the active signal.
- Trigger matches activate nodes in the DAG; they do not bypass dependency checks.

Example:

- `build-core` is auto-selected by signal `repo-change`
- `update-docs` is activated by a matching propagation trigger from `build-core`
- `update-docs` depends on `prepare-docs-context`
- the scheduler must run `prepare-docs-context` before `update-docs`, even though only `build-core` matched the signal directly

This keeps stage-5 signal semantics intact while making downstream scheduling dependency-aware.

## Repository-Scoped Context Storage And Working Directory

Stage 6 keeps the existing file-backed context bag, but scopes it to each execution working directory.

Rules:

- The context directory is still `working_dir / ".propagate-context"`.
- For repository-bound executions, that means each repository gets its own local bag.
- For executions without `repository`, the bag remains `Path.cwd() / ".propagate-context"`.
- Context written in one repository is not automatically visible in another repository.
- Stage 6 does not add a shared cross-repository context store.

This is an intentional constraint. It preserves stage-2 and stage-3 locality rather than inventing global or upstream-task context in the final stage.

### Signal namespace

The `:signal` namespace must also become repository-scoped.

Behavior:

- Before the first execution runs in a given working directory for the current `propagate run`, clear that directory's `:signal` namespace.
- If an active signal exists, repopulate that directory's `:signal.*` keys using the same serialization rules from stage 5.
- Reuse the existing context-write helpers; do not introduce a second storage mechanism.

Tracking initialization per working directory is preferable to doing one global initialization at process start, because a stage-6 run may touch multiple repositories.

### CLI context commands

Keep the CLI unchanged:

- `propagate context set ...`
- `propagate context get ...`

They still operate on `Path.cwd()`. Stage 6 does not add `--repository` flags. If a user wants to inspect a repository-local context bag, they must invoke the command from that repository directory.

## Failure Behavior

Invalid config must fail during `load_config()`:

- unsupported `repositories` shapes
- invalid repository names
- empty or invalid repository paths
- unknown repository references from `executions.<name>.repository`
- unknown execution references in `depends_on`
- duplicate dependencies
- self-dependencies
- unknown execution names in propagation triggers
- any cycle in the combined dependency/trigger graph

Runtime failures must remain user-facing `PropagateError`s:

- repository working directory does not exist
- repository path is not a directory
- a triggered execution is missing at runtime
- an execution fails in any repository
- a git operation fails in the routed repository
- hook, context-source, prompt, or agent failures in the routed repository

Missing working-directory handling:

- validate the execution working directory immediately before that execution starts
- include both execution name and repository name when available
- fail before running hooks, agent commands, or git setup for that execution

Cross-repository failure semantics:

- if execution `A` in repository `core` succeeds and execution `B` in repository `docs` fails, stop the run immediately
- do not roll back successful earlier executions
- do not roll back context writes, commits, pushes, or PRs that already happened in earlier repositories
- do not attempt compensating actions in other repositories

Representative errors:

- `Execution 'update-docs' references unknown repository 'docs'.`
- `Execution 'update-docs' depends_on references unknown execution 'prepare-docs'.`
- `Execution graph contains a cycle: build-core -> update-docs -> build-core.`
- `Execution 'update-docs' cannot start in repository 'docs': working directory does not exist: /repos/docs-site`
- `Execution 'sdk-java' failed while running in repository 'sdk-java'.`

## Logging

Use `logging`, not `print()`.

Add `INFO` logs for:

- repository routing for each execution
- signal-context initialization per working directory
- dependency activation when a node becomes active
- trigger activation when a completed execution activates another node
- scheduler decisions when multiple nodes are runnable

Do not log:

- prompt contents
- context values
- signal payload contents
- raw subprocess stdout on success

## Implementation Shape

Keep the change in `propagate.py` with small helper additions.

Recommended additions:

- `RepositoryConfig`
- `ExecutionConfig.repository`
- `ExecutionConfig.depends_on`
- `Config.repositories`
- `parse_repositories()`
- `parse_repository()`
- `parse_execution_dependencies()`
- `validate_execution_graph_is_acyclic()`
- `resolve_execution_working_dir(execution, config, invocation_dir)`
- `ensure_execution_working_dir(execution, working_dir)`
- `activate_execution_with_dependencies(...)`
- `select_next_runnable_execution(...)`
- `prepare_signal_context_for_working_dir(...)`

Recommended runtime refactor:

- change `RuntimeContext` so it carries the invocation directory and active signal, not one fixed working directory for the whole run
- derive the working directory per execution before calling the existing execution runner
- keep the existing sub-task and git helpers mostly unchanged by passing them an execution-scoped runtime context or explicit working directory

The important boundary is behavioral:

- prompt resolution stays config-relative
- execution work stays repository-relative
- context stays local to the execution working directory
- signals and triggers keep their stage-5 meaning
- scheduling becomes dependency-aware and deterministic across repositories
