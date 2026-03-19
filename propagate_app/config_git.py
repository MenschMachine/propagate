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
    validate_allowed_keys(branch_data, {"name", "base", "reuse", "name_key", "name_template"}, location)
    reuse = branch_data.get("reuse", True)
    if not isinstance(reuse, bool):
        raise PropagateError(f"{location}.reuse must be a boolean when provided.")
    name = optional_non_empty_string(branch_data.get("name"), f"{location}.name")
    name_key = None
    if "name_key" in branch_data:
        validated = validate_context_key(branch_data["name_key"])
        if not validated.startswith(":"):
            raise PropagateError(f"{location}.name_key must use a reserved ':'-prefixed context key.")
        name_key = validated
    name_template = optional_non_empty_string(branch_data.get("name_template"), f"{location}.name_template")
    if sum(value is not None for value in (name, name_key, name_template)) > 1:
        raise PropagateError(f"{location} must define at most one of 'name', 'name_key', or 'name_template'.")
    return GitBranchConfig(
        name=name,
        base=optional_non_empty_string(branch_data.get("base"), f"{location}.base"),
        reuse=reuse,
        name_key=name_key,
        name_template=name_template,
    )


def parse_git_commit_config(
    execution_name: str,
    commit_data: Any,
    context_source_names: set[str],
) -> GitCommitConfig:
    location = f"Execution '{execution_name}' git.commit"
    if not isinstance(commit_data, dict):
        raise PropagateError(f"{location} must be a mapping.")
    validate_allowed_keys(commit_data, {"message_source", "message_key", "message_template"}, location)
    message_source = commit_data.get("message_source")
    message_key = commit_data.get("message_key")
    message_template = optional_non_empty_string(commit_data.get("message_template"), f"{location}.message_template")
    if sum(value is not None for value in (message_source, message_key, message_template)) != 1:
        raise PropagateError(
            f"{location} must define exactly one of 'message_source', 'message_key', or 'message_template'."
        )
    if message_source is not None:
        source_name = validate_context_source_name(message_source)
        if source_name not in context_source_names:
            raise PropagateError(f"{location}.message_source references unknown context source '{source_name}'.")
        return GitCommitConfig(message_source=source_name, message_key=None, message_template=None)
    if message_template is not None:
        return GitCommitConfig(message_source=None, message_key=None, message_template=message_template)
    validated_key = validate_context_key(message_key)
    if not validated_key.startswith(":"):
        raise PropagateError(f"{location}.message_key must use a reserved ':'-prefixed context key.")
    return GitCommitConfig(message_source=None, message_key=validated_key, message_template=None)


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
    validate_allowed_keys(pr_data, {"base", "draft", "title_key", "body_key", "title_template", "body_template", "number_key"}, location)
    draft = pr_data.get("draft", False)
    if not isinstance(draft, bool):
        raise PropagateError(f"{location}.draft must be a boolean when provided.")
    title_key = None
    if "title_key" in pr_data:
        validated = validate_context_key(pr_data["title_key"])
        if not validated.startswith(":"):
            raise PropagateError(f"{location}.title_key must use a reserved ':'-prefixed context key.")
        title_key = validated
    body_key = None
    if "body_key" in pr_data:
        validated = validate_context_key(pr_data["body_key"])
        if not validated.startswith(":"):
            raise PropagateError(f"{location}.body_key must use a reserved ':'-prefixed context key.")
        body_key = validated
    title_template = optional_non_empty_string(pr_data.get("title_template"), f"{location}.title_template")
    body_template = optional_non_empty_string(pr_data.get("body_template"), f"{location}.body_template")
    if title_key is not None and title_template is not None:
        raise PropagateError(f"{location} must define at most one of 'title_key' or 'title_template'.")
    if body_key is not None and body_template is not None:
        raise PropagateError(f"{location} must define at most one of 'body_key' or 'body_template'.")
    number_key = None
    if "number_key" in pr_data:
        validated = validate_context_key(pr_data["number_key"])
        if not validated.startswith(":"):
            raise PropagateError(f"{location}.number_key must use a reserved ':'-prefixed context key.")
        number_key = validated
    return GitPrConfig(
        base=optional_non_empty_string(pr_data.get("base"), f"{location}.base"),
        draft=draft,
        title_key=title_key,
        body_key=body_key,
        title_template=title_template,
        body_template=body_template,
        number_key=number_key,
    )
