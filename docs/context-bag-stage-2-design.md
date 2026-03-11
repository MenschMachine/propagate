# Context Bag Stage 2 Design

## Scope

Stage 2 adds a local, file-backed context bag to the existing stage 1 runtime. It introduces `propagate context set <key> <value>`, `propagate context get <key>`, and prompt augmentation during `propagate run`. It does not add hooks, git operations, signals, includes, defaults, or guidelines.

The implementation should stay in `propagate.py`, keep `PyYAML` as the only external dependency, and preserve stage 1 `run` behavior except for the new context injection when local context exists.

## CLI changes

`build_parser()` should keep the existing `run` subcommand and add a top-level `context` command with nested subcommands:

```text
propagate run --config <path> [--execution <name>]
propagate context set <key> <value>
propagate context get <key>
```

Suggested parser shape:

- `subparsers = parser.add_subparsers(dest="command", required=True)`
- `run` remains unchanged
- `context_parser = subparsers.add_parser("context", help="Manage local context values.")`
- `context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)`
- `set` takes positional `key` and `value`
- `get` takes positional `key`

`main()` should dispatch to `run_command()`, `context_set_command()`, or `context_get_command()`.

## Context store location

The local context directory is always derived from the invocation working directory:

```python
context_dir = Path.cwd() / ".propagate-context"
```

This applies to both `propagate context ...` and `propagate run ...`. The store is intentionally tied to the repo the user is operating on, not to the config file location.

Prompt file paths must continue to resolve relative to the config file exactly as they do in stage 1.

## Key validation

Keys are stored literally as filenames under `.propagate-context`, so validation must make the filename safe and keep future context-source keys representable on disk.

Allowed key format:

```text
^:?[A-Za-z0-9][A-Za-z0-9._-]*$
```

Rules:

- Reject empty keys.
- Reject any key containing `/` or `\\`.
- Reject `.` and `..`.
- Reject whitespace.
- Reject keys outside the allowed character set above.
- Allow a single leading `:` so stage 3 hooks can write keys such as `:openapi-spec`.
- Treat `:`-prefixed keys as reserved for future context-source usage.
  Stage 2 still allows manual `set` and `get` on them, but the design note and help text should call out that those keys are reserved by convention.
- Do not encode or transform keys before writing them to disk. The filename is the key.

This keeps stage 2 simple while leaving room for stage 3 hooks to call `propagate context set :source-name`.

## `context set` behavior

`context set` should:

1. Validate the key.
2. Create `.propagate-context` with `mkdir(parents=True, exist_ok=True)` if needed.
3. Write the provided value as UTF-8 text to `.propagate-context/<key>`.
4. Overwrite any existing value for that key completely.

Write semantics:

- The stored value is exactly the CLI argument value, with no added newline.
- Use an atomic replace pattern in the same directory if practical:
  write to a temporary file in `.propagate-context`, then `Path.replace()` onto the target.
- On success, log an `INFO` message naming the stored key.
- On validation or filesystem failure, raise `PropagateError` with a clear user-facing message.

## `context get` behavior

`context get` should:

1. Validate the key.
2. Read `.propagate-context/<key>` as UTF-8 text.
3. Write the value to stdout exactly with `sys.stdout.write(value)`.

Failure behavior:

- If the key does not exist, raise `PropagateError` with a clear message, for example:
  `Context key 'release_version' was not found in /repo/.propagate-context.`
- If the path exists but is not a regular file, raise `PropagateError`.
- Do not log the value itself.
- Avoid success logging for `context get` so shell consumers get only the stored value on stdout.

## `run` integration

Stage 1 flow stays intact:

1. Load config.
2. Select execution.
3. Run sub-tasks sequentially.
4. Read each prompt file.
5. Write a temporary prompt file.
6. Substitute `{prompt_file}` into `agent.command`.
7. Execute the agent command in the invocation working directory.
8. Remove the temporary prompt file.

Stage 2 inserts one step between prompt-file read and temporary prompt-file write:

1. Read the prompt file.
2. Load local context from `Path.cwd() / ".propagate-context"`.
3. If context exists, append a deterministic `Context` section to the prompt text.
4. Write the augmented prompt text to the temporary prompt file.

Context should be loaded per sub-task, not once per execution. That keeps behavior correct if a prior sub-task or an external process updates `.propagate-context` before a later sub-task runs.

If `.propagate-context` does not exist or contains no valid context files, `run` should behave exactly like stage 1.

## Loading context values

Add a helper that reads local context into an ordered mapping or a sorted list of `(key, value)` pairs.

Loading rules:

- If `.propagate-context` does not exist, return an empty collection.
- Read only regular files directly inside `.propagate-context`.
- Sort by filename/key in ascending lexical order before rendering.
- Read file contents as UTF-8.

Invalid store entries:

- Ignore non-file entries with a warning.
- Treat any regular file whose name fails key validation as an error.

The store should normally only contain files created by `context set`, so an invalid filename indicates manual corruption and should fail clearly.

## Deterministic rendering format

Use this exact Markdown structure:

```markdown
## Context

### key-one
value one

### key-two
value two
```

Rendering rules:

- Keys are sorted lexically before rendering.
- The section header is exactly `## Context`.
- Each key gets a `### <key>` heading.
- Each value is inserted verbatim below its heading.
- Ensure a blank line separates entries.
- If a stored value does not end in `\n`, add one during rendering so the next heading starts on its own line.

Prompt concatenation rules:

- If no context exists, return the original prompt text unchanged.
- If context exists, append the section after the original prompt with one blank line of separation.
- Preserve the original prompt contents as much as possible; only add the separator and context section.

One implementation-friendly separator rule is:

- If the prompt already ends with `\n\n`, append the context section directly.
- If it ends with a single trailing newline, append one more newline before `## Context`.
- Otherwise append `\n\n` before `## Context`.

## Logging and error handling

Keep the existing stage 1 error model:

- Helpers raise `PropagateError` for user-facing validation and IO failures.
- `main()` catches `PropagateError`, logs the message at `ERROR`, and returns exit code `1`.
- `KeyboardInterrupt` still returns `130`.

Additional logging expectations:

- Preserve existing `run` lifecycle `INFO` logs.
- `context set` logs a concise `INFO` success message.
- `context get` should not log on success.
- `run` may log a concise `INFO` line when context is loaded for a sub-task, but it should not log full context values.
- Temporary prompt cleanup stays best-effort with a warning on failure.

## Stage boundary

Stage 2 should remain a narrow extension of stage 1:

- Keep all logic in `propagate.py`.
- Keep `PyYAML` as the only non-stdlib dependency.
- Do not add config sections for hooks, context sources, git, signals, includes, defaults, or guidelines.
- Do not change agent execution semantics beyond prompt augmentation.
- Continue to resolve prompt paths relative to the config file.

Because the runtime is now stage 2, bump the config schema marker from `version: "1"` to `version: "2"` and update `load_config()` to require `"2"`. The rest of the config structure stays the same.

## Bootstrap chain output

The stage 2 implementation must also advance the self-hosting chain:

- Update `config/propagate.yaml` to target stage 3.
- Rename the execution from `build-stage2` to `build-stage3`.
- Point its sub-task prompts at:
  - `./prompts/design-stage3.md`
  - `./prompts/implement-stage3.md`
  - `./prompts/review-stage3.md`
- Set the config version to `"2"`.

The new stage 3 prompts should instruct the next run to add:

- sub-task hooks: `before`, `after`, `on_failure`
- context-source support, including the `:source-name` convention
- hook-driven loading of context sources into the local context bag

The prompts can be leaner than the stage 2 prompts because stage 2 now has a context bag, but they still need enough inline context to continue the bootstrapping chain without any hook system already in place.

## Suggested helper additions

To keep the implementation clear inside one file, add small helpers with narrow responsibilities:

- `get_context_dir(working_dir: Path) -> Path`
- `validate_context_key(key: str) -> str`
- `context_set_command(key: str, value: str, working_dir: Path) -> int`
- `context_get_command(key: str, working_dir: Path) -> int`
- `write_context_value(context_dir: Path, key: str, value: str) -> None`
- `read_context_value(context_dir: Path, key: str) -> str`
- `load_local_context(context_dir: Path) -> list[tuple[str, str]]`
- `render_context_section(items: list[tuple[str, str]]) -> str`
- `append_context_to_prompt(prompt_contents: str, items: list[tuple[str, str]]) -> str`

This keeps the change implementation-ready without expanding stage 2 beyond the intended boundary.
