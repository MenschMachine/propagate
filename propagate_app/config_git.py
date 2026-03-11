from typing import Any

from .errors import PropagateError
from .models import GitBranchConfig, GitCommitConfig, GitConfig, GitPrConfig, GitPushConfig
from .validation import (
    optional_non_empty_string,
    validate_allowed_keys,
    validate_context_key,
    validate_context_source_name,
)


def parse_git_config(execution_name: str, git_data: Any, context_source_names: set[str]) -> GitConfig | None:
    if git_data is None:
        return None
    if not isinstance(git_data, dict):
        raise PropagateError(f"Execution '{execution_name}' git config must be a mapping.")
    validate_allowed_keys(git_data, {"branch", "commit", "push", "pr"}, f"Execution '{execution_name}' git")
    branch = parse_git_branch_config(execution_name, git_data.get("branch"))
    commit = parse_git_commit_config(execution_name, git_data.get("commit"), context_source_names)
    push = parse_git_push_config(execution_name, git_data.get("push"))
    pr = parse_git_pr_config(execution_name, git_data.get("pr"))
    if pr is not None and push is None:
        raise PropagateError(f"Execution '{execution_name}' git.pr requires git.push to be configured.")
    return GitConfig(branch=branch, commit=commit, push=push, pr=pr)


def parse_git_branch_config(execution_name: str, branch_data: Any) -> GitBranchConfig:
    location = f"Execution '{execution_name}' git.branch"
    if not isinstance(branch_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(branch_data, {"name", "base", "reuse"}, location)
    reuse = branch_data.get("reuse", True)
    if not isinstance(reuse, bool):
        raise PropagateError(f"{location}.reuse must be a boolean when provided.")
    return GitBranchConfig(
        name=optional_non_empty_string(branch_data.get("name"), f"{location}.name"),
        base=optional_non_empty_string(branch_data.get("base"), f"{location}.base"),
        reuse=reuse,
    )


def parse_git_commit_config(
    execution_name: str,
    commit_data: Any,
    context_source_names: set[str],
) -> GitCommitConfig:
    location = f"Execution '{execution_name}' git.commit"
    if not isinstance(commit_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(commit_data, {"message_source", "message_key"}, location)
    message_source = commit_data.get("message_source")
    message_key = commit_data.get("message_key")
    if (message_source is None) == (message_key is None):
        raise PropagateError(f"{location} must define exactly one of 'message_source' or 'message_key'.")
    if message_source is not None:
        source_name = validate_context_source_name(message_source)
        if source_name not in context_source_names:
            raise PropagateError(f"{location}.message_source references unknown context source '{source_name}'.")
        return GitCommitConfig(message_source=source_name, message_key=None)
    validated_key = validate_context_key(message_key)
    if not validated_key.startswith(":"):
        raise PropagateError(f"{location}.message_key must use a reserved ':'-prefixed context key.")
    return GitCommitConfig(message_source=None, message_key=validated_key)


def parse_git_push_config(execution_name: str, push_data: Any) -> GitPushConfig | None:
    if push_data is None:
        return None
    location = f"Execution '{execution_name}' git.push"
    if not isinstance(push_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(push_data, {"remote"}, location)
    remote = push_data.get("remote")
    if not isinstance(remote, str) or not remote.strip():
        raise PropagateError(f"{location}.remote must be a non-empty string.")
    return GitPushConfig(remote=remote)


def parse_git_pr_config(execution_name: str, pr_data: Any) -> GitPrConfig | None:
    if pr_data is None:
        return None
    location = f"Execution '{execution_name}' git.pr"
    if not isinstance(pr_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(pr_data, {"base", "draft"}, location)
    draft = pr_data.get("draft", False)
    if not isinstance(draft, bool):
        raise PropagateError(f"{location}.draft must be a boolean when provided.")
    return GitPrConfig(base=optional_non_empty_string(pr_data.get("base"), f"{location}.base"), draft=draft)
