from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    command: str


@dataclass(frozen=True)
class ContextSourceConfig:
    name: str
    command: str


@dataclass(frozen=True)
class RepositoryConfig:
    name: str
    path: Path | None
    url: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class SignalFieldConfig:
    field_type: str
    required: bool


@dataclass(frozen=True)
class SignalConfig:
    name: str
    payload: dict[str, SignalFieldConfig]


@dataclass(frozen=True)
class GitBranchConfig:
    name: str | None
    base: str | None
    reuse: bool


@dataclass(frozen=True)
class GitCommitConfig:
    message_source: str | None
    message_key: str | None


@dataclass(frozen=True)
class GitPushConfig:
    remote: str


@dataclass(frozen=True)
class GitPrConfig:
    base: str | None
    draft: bool
    title_key: str | None = None
    body_key: str | None = None


@dataclass(frozen=True)
class GitConfig:
    branch: GitBranchConfig
    commit: GitCommitConfig
    push: GitPushConfig | None
    pr: GitPrConfig | None


@dataclass(frozen=True)
class SubTaskConfig:
    task_id: str
    prompt_path: Path | None
    before: list[str]
    after: list[str]
    on_failure: list[str]


@dataclass
class GitRunState:
    starting_branch: str | None = None
    selected_branch: str | None = None
    commit_message: str | None = None


@dataclass(frozen=True)
class ExecutionConfig:
    name: str
    repository: str
    depends_on: list[str]
    signals: list[str]
    sub_tasks: list[SubTaskConfig]
    git: GitConfig | None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    on_failure: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PropagationTriggerConfig:
    after: str
    run: str
    on_signal: str | None


@dataclass(frozen=True)
class Config:
    version: str
    agent: AgentConfig
    repositories: dict[str, RepositoryConfig]
    context_sources: dict[str, ContextSourceConfig]
    signals: dict[str, SignalConfig]
    propagation_triggers: list[PropagationTriggerConfig]
    executions: dict[str, ExecutionConfig]
    config_path: Path


@dataclass(frozen=True)
class ActiveSignal:
    signal_type: str
    payload: dict[str, Any]
    source: str


@dataclass(frozen=True)
class RuntimeContext:
    agent_command: str
    context_sources: dict[str, ContextSourceConfig]
    active_signal: ActiveSignal | None
    initialized_signal_context_dirs: set[Path]
    working_dir: Path = field(default_factory=Path)
    context_root: Path = field(default_factory=Path)
    execution_name: str = ""
    task_id: str = ""
    git_state: GitRunState | None = None


@dataclass
class ExecutionScheduleState:
    active_names: set[str]
    completed_names: set[str]
    completed_tasks: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class RunState:
    config_path: Path
    initial_execution: str
    schedule: ExecutionScheduleState
    active_signal: ActiveSignal | None
    cloned_repos: dict[str, Path]
    initialized_signal_context_dirs: set[Path]


@dataclass(frozen=True)
class PreparedGitExecution:
    starting_branch: str
    selected_branch: str


@dataclass(frozen=True)
class ExecutionGraph:
    execution_order: tuple[str, ...]
    triggers_by_after: dict[str, tuple[PropagationTriggerConfig, ...]]


@dataclass(frozen=True)
class ExecutionRouting:
    working_dir: Path
    location_display: str
    repository_name: str
