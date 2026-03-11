# Context Bag Stage 2 Design

## Scope

Stage 2 is a narrow extension of the current stage-1 CLI in [`propagate.py`](/Users/michael/Code/TFC/propagate/propagate.py). It adds:

- `propagate context set <key> <value>`
- `propagate context get <key>`
- a local file-backed context bag under `.propagate-context`
- automatic prompt augmentation during `propagate run`

Stage 2 does not add hooks, git automation, signals, propagation, includes, defaults, guidelines, or package restructuring.

The implementation should remain in `propagate.py`, continue to use `PyYAML` as the only external dependency, and preserve the existing stage-1 run lifecycle unless this document explicitly extends it.

## CLI Shape

Stage 2 must expose exactly these entry points:

```text
propagate run --config <path> [--execution <name>]
propagate context set <key> <value>
propagate context get <key>
```

`build_parser()` should keep the existing top-level `run` command and add a top-level `context` command with nested `set` and `get` subcommands.

Recommended parser shape:

```python
parser = argparse.ArgumentParser(prog="propagate")
subparsers = parser.add_subparsers(dest="command", required=True)

run_parser = subparsers.add_parser("run", help="Run an execution from a config file.")
run_parser.add_argument("--config", required=True, help="Path to the Propagate YAML config.")
run_parser.add_argument("--execution", help="Execution name to run.")

context_parser = subparsers.add_parser("context", help="Manage local context values.")
context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)

set_parser = context_subparsers.add_parser("set", help="Store a local context value.")
set_parser.add_argument("key")
set_parser.add_argument("value")

get_parser = context_subparsers.add_parser("get", help="Read a local context value.")
get_parser.add_argument("key")
```

`main()` should dispatch to:

- `run_command(args.config, args.execution)`
- `context_set_command(args.key, args.value, Path.cwd())`
- `context_get_command(args.key, Path.cwd())`

The run command shape stays unchanged from stage 1.

## Storage Model

The local context directory is always:

```python
Path.cwd() / ".propagate-context"
```

This is based on the invocation working directory, not the config file location. Prompt paths continue to resolve relative to the config file exactly as they do in stage 1.

Storage format:

- one direct child file per key
- filename is the key, stored literally
- file contents are the UTF-8 value for that key
- no metadata files
- no filename encoding, hashing, escaping, or subdirectories

Examples:

```text
.propagate-context/release-version
.propagate-context/:openapi-spec
```

This keeps the store simple now and leaves room for stage-3 named context sources to populate reserved `:`-prefixed keys later.

## Key Validation

Keys are stored as literal filenames, so validation must happen before any filesystem operation.

Validation rules:

1. Reject an empty key.
2. Allow at most one `:` and only as the first character.
3. After removing one optional leading `:`, require a non-empty body.
4. Reject any key body equal to `.` or `..`.
5. Reject any key containing `/`, `\\`, or any Unicode whitespace.
6. Reject traversal-like names by validating the raw key before path construction and by never normalizing or encoding it.
7. Keep filenames literal; the accepted key string is the on-disk filename.

Implementation-ready rule:

```python
CONTEXT_KEY_PATTERN = re.compile(r"^:?[A-Za-z0-9][A-Za-z0-9._-]*$")
```

Additional checks:

- `:` by itself is invalid
- `:.` and `:..` are invalid
- `.` and `..` are invalid

This character set is intentionally conservative. It supports the current examples such as `release-version`, `sdk_version`, and future stage-3 source keys like `:openapi-spec` without introducing path ambiguity.

## `context set`

Behavior:

1. Validate the key.
2. Derive `context_dir = Path.cwd() / ".propagate-context"`.
3. Create the directory with `mkdir(parents=True, exist_ok=True)`.
4. Overwrite the stored value completely.
5. Write UTF-8 text with no automatic newline.
6. Return exit code `0` on success.

Write semantics:

- the stored bytes are exactly `value.encode("utf-8")`
- an existing file is replaced, not appended to
- no newline is added if the CLI argument does not contain one

Atomicity:

- use a temporary file in the same directory, then replace the target with `Path.replace()`
- this is preferred over direct write because it avoids partially-written context values if the process is interrupted

Suggested helper shape:

```python
def write_context_value(context_dir: Path, key: str, value: str) -> None:
    ...
```

Logging:

- `context set` may log a concise `INFO` success line
- do not log the stored value

Representative success log:

```text
INFO Stored context key 'release-version'.
```

Representative errors:

- `Invalid context key ':'.`
- `Invalid context key '../secret'.`
- `Failed to write context key 'release-version' in /repo/.propagate-context: ...`

## `context get`

Behavior:

1. Validate the key.
2. Read exactly one file: `.propagate-context/<key>`.
3. Write its exact contents to stdout.
4. Return exit code `0` on success.

Read semantics:

- read as UTF-8 text
- write with `sys.stdout.write(value)`
- do not append a newline
- do not log the value

Failure behavior:

- if the directory does not exist, fail clearly
- if the key file does not exist, fail clearly
- if the path exists but is not a regular file, fail clearly
- if UTF-8 decoding fails, raise `PropagateError`

Representative missing-key error:

```text
Context key 'release-version' was not found in /repo/.propagate-context.
```

## `run` Integration

Stage 1 currently does:

1. Load config.
2. Select execution.
3. Read each prompt file.
4. Write a temporary prompt file.
5. Substitute `{prompt_file}` into the configured agent command.
6. Run the agent command in `Path.cwd()`.
7. Remove the temporary prompt file.

Stage 2 inserts local-context loading and rendering between prompt read and temporary-file write:

1. Read the prompt file.
2. Load local context from `Path.cwd() / ".propagate-context"`.
3. Sort keys deterministically.
4. Append a Markdown section labeled exactly `## Context` when any context exists.
5. Write the augmented prompt to the temporary file.
6. Continue with the stage-1 agent execution flow unchanged.

Context must be loaded fresh for every sub-task, not once per execution. That keeps later sub-tasks correct if an earlier sub-task or an external command changes `.propagate-context`.

If the context directory does not exist, `run` behaves exactly like stage 1.

## Loading Rules

`run` should load only direct children of `.propagate-context`.

Rules:

- if the directory does not exist, return an empty list
- if the path exists but is not a directory, raise `PropagateError`
- each direct child must be a regular file
- each filename must pass the same key validation used by `context set` and `context get`
- read each file as UTF-8 text
- sort by literal key string in ascending lexical order before rendering

Store corruption policy:

- fail clearly on invalid filenames
- fail clearly on non-file entries

This is stricter than silently skipping entries and is easier to reason about during self-hosting. Stage 2 owns the directory format, so unexpected entries should surface as user-facing errors.

## Rendering

When context exists, append this exact Markdown structure:

```markdown
## Context

### key-one
value one

### key-two
value two
```

Rendering rules:

- section header must be exactly `## Context`
- keys render in deterministic sorted order
- each key renders as `### <key>`
- each value is inserted verbatim, with no escaping or transformation
- if a value does not end with `\n`, add one during rendering so the next heading starts on its own line
- separate entries with a single blank line

One implementation-friendly renderer:

```python
def render_context_section(items: list[tuple[str, str]]) -> str:
    parts = ["## Context", ""]
    for index, (key, value) in enumerate(items):
        parts.append(f"### {key}")
        parts.append(value if value.endswith("\n") else f"{value}\n")
        if index != len(items) - 1:
            parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"
```

Prompt concatenation rules:

- if there is no context, return the original prompt unchanged
- if context exists, append one blank line between the original prompt and the `## Context` section
- preserve the original prompt contents otherwise

Simple separator rule:

- prompt ends with `\n\n`: append the section directly
- prompt ends with `\n`: append one more newline, then the section
- otherwise append `\n\n`, then the section

## Logging And Errors

Keep the stage-1 error model:

- helpers raise `PropagateError` for user-facing validation and IO failures
- `main()` catches `PropagateError`, logs the message at `ERROR`, and returns `1`
- `KeyboardInterrupt` still returns `130`
- temporary prompt cleanup remains best-effort with a warning on failure

Logging expectations:

- preserve existing run lifecycle logs
- `context set` may log success
- `context get` should not log on success
- `run` should not log context values
- optional new run logging may mention the count of loaded context keys, but it should stay concise

Representative run logs:

```text
INFO Running execution 'build-stage3' with 6 sub-task(s).
INFO Running sub-task 'design' for execution 'build-stage3' using prompt '/repo/config/prompts/design-stage3.md'.
INFO Execution 'build-stage3' completed successfully.
```

## Implementation Shape

Keep the implementation in `propagate.py` and add small helpers rather than restructuring the package.

Suggested helpers:

- `get_context_dir(working_dir: Path) -> Path`
- `validate_context_key(key: str) -> str`
- `context_set_command(key: str, value: str, working_dir: Path) -> int`
- `context_get_command(key: str, working_dir: Path) -> int`
- `write_context_value(context_dir: Path, key: str, value: str) -> None`
- `read_context_value(context_dir: Path, key: str) -> str`
- `load_local_context(context_dir: Path) -> list[tuple[str, str]]`
- `render_context_section(items: list[tuple[str, str]]) -> str`
- `append_context_to_prompt(prompt_text: str, items: list[tuple[str, str]]) -> str`

Minimal code changes outside those helpers:

- import `re` and `sys`
- extend `build_parser()`
- extend `main()` dispatch
- change `load_config()` to require `version == "2"` after the stage-2 bootstrap output is written
- update `run_sub_task()` to append context before writing the temporary prompt

## Tests

Stage 2 should add direct tests for the new behavior. Since the runtime remains a single Python file with no extra dependencies, use stdlib `unittest` and temporary directories unless a test harness already exists by the implementation step.

Required coverage:

1. `context set` creates `.propagate-context` and writes the exact UTF-8 value with no newline added.
2. `context set` overwrites an existing value completely.
3. `context get` returns the exact stored value to stdout.
4. `context get` fails clearly for a missing key.
5. invalid keys are rejected for both `set` and `get`.
6. `run` injects the `## Context` block when context exists.
7. rendered context order is deterministic for multiple keys.
8. `run` is unchanged when `.propagate-context` is absent.
9. store corruption during `run` fails clearly for an invalid filename or non-file entry.

Recommended test shape:

- unit-test the helpers directly
- add one CLI-level smoke test for parser dispatch or `main()`
- use a temporary working directory and patch `Path.cwd()` or invoke the CLI with `cwd=...`

## Stage-3 Bootstrap Output

Stage 2 must advance the self-hosting chain to stage 3.

Required repository output:

1. Update [`config/propagate.yaml`](/Users/michael/Code/TFC/propagate/config/propagate.yaml) to `version: "2"`.
2. Rename the execution from `build-stage2` to `build-stage3`.
3. Use the standard six-step chain:
   - `design`
   - `implement`
   - `test`
   - `refactor`
   - `verify`
   - `review`
4. In [`config/propagate.yaml`](/Users/michael/Code/TFC/propagate/config/propagate.yaml), point those sub-tasks at:
   - `./prompts/design-stage3.md`
   - `./prompts/implement-stage3.md`
   - `./prompts/test-stage3.md`
   - `./prompts/refactor-stage3.md`
   - `./prompts/verify-stage3.md`
   - `./prompts/review-stage3.md`
5. Produce these files:
   - [`config/prompts/design-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/design-stage3.md)
   - [`config/prompts/implement-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/implement-stage3.md)
   - [`config/prompts/test-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/test-stage3.md)
   - [`config/prompts/refactor-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/refactor-stage3.md)
   - [`config/prompts/verify-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/verify-stage3.md)
   - [`config/prompts/review-stage3.md`](/Users/michael/Code/TFC/propagate/config/prompts/review-stage3.md)

Stage-3 prompt content must tell the next run to add only stage-3 features:

- `before`, `after`, and `on_failure` hooks
- named `context_sources` in config
- hook-driven loading into the local bag via keys like `:openapi-spec`

Stage 3 must continue to use the same local bag introduced in stage 2. It does not add a second context storage path.

Because this repository already contains some stage-3 prompt files from an earlier draft, the stage-2 implementation should treat the bootstrap output above as authoritative and replace any outdated three-step stage-3 prompt set with the required six-step chain.

## Stage Boundary

Stage 2 deliberately stops here:

- no hooks
- no git automation
- no signals or propagation triggers
- no includes or defaults
- no guidelines
- no package restructuring

That boundary matters for later stages:

- stage 3 loads named context sources into this bag
- stage 4 uses bag values for commit metadata
- stage 5 injects signal metadata into the bag
- stage 6 expands context scope beyond the local store

The stage-2 design should therefore optimize for simple, literal, deterministic local storage now rather than prematurely adding higher-level abstractions.
