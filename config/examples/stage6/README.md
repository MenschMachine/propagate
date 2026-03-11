## Stage 6 Example Bundle

This bundle shows the configuration surface that the current stage-6 runtime in [`propagate.py`](/Users/michael/Code/TFC/propagate/propagate.py) actually supports today.

It is intentionally separate from [`docs/CONFIG_REFERENCE.md`](/Users/michael/Code/TFC/propagate/docs/CONFIG_REFERENCE.md). The reference document is broader and aspirational in places; this bundle only demonstrates features that the runtime parses and executes now.

### What the bundle demonstrates

- Signal-driven execution selection with a typed payload schema.
- Cross-repository routing with repository-local `.propagate-context` state.
- Execution-level dependencies and a simple fan-out/fan-in DAG.
- `before`, `after`, and `on_failure` hooks.
- Context sources loaded with `:name` hook actions.
- Manual shell hook actions that write extra local context.
- Git automation with both commit message modes:
  `message_key` in `archive-review`.
  `message_source`, `push`, and `pr` in `publish-docs`.

### Bundle layout

- [`propagate.yaml`](/Users/michael/Code/TFC/propagate/config/examples/stage6/propagate.yaml): fully commented example config.
- [`signals/repo-change.yaml`](/Users/michael/Code/TFC/propagate/config/examples/stage6/signals/repo-change.yaml): sample signal file that exercises every supported payload type.
- [`prompts/`](/Users/michael/Code/TFC/propagate/config/examples/stage6/prompts): prompt set referenced by the config.
- [`repos/core-api`](/Users/michael/Code/TFC/propagate/config/examples/stage6/repos/core-api): placeholder repository path for routed executions.
- [`repos/docs-site`](/Users/michael/Code/TFC/propagate/config/examples/stage6/repos/docs-site): placeholder repository path for routed executions and git demos.
- [`workspace`](/Users/michael/Code/TFC/propagate/config/examples/stage6/workspace): suggested invocation directory for executions that do not set `repository`.

### Quick start

To inspect parsing only:

```bash
python3 -m unittest tests.test_example_stage6_bundle
```

To run the non-git DAG demo from the example workspace:

```bash
cd config/examples/stage6/workspace
python3 ../../../../propagate.py run \
  --config ../propagate.yaml \
  --signal-file ../signals/repo-change.yaml
```

That run auto-selects `triage-change`, fans out to `prepare-core-context` and `lint-docs`, waits for both, then runs `update-docs` and `review-docs`.

The bundled `agent.command` is intentionally harmless: it copies the rendered prompt into `PROPAGATE_EXAMPLE_OUTPUT.md` in the current working directory so you can inspect exactly what Propagate assembled.

### Running the git examples

`archive-review` and `publish-docs` are manual executions that demonstrate git automation. Before running them, initialize `repos/docs-site` as a git repository with a `main` branch and at least one commit.

`publish-docs` also expects:

- a push target named `origin`
- the GitHub CLI `gh` on `PATH`
- auth configured so `gh pr create` can succeed

If you only want to exercise local branch and commit creation, run `archive-review`.
