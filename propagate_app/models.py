from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import zmq


@dataclass(frozen=True)
class AgentConfig:
    agents: dict[str, str]  # name -> command string
    default_agent: str  # name of default agent


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
    check: str | None = None


@dataclass(frozen=True)
class ExecutionSignalConfig:
    signal_name: str
    when: dict[str, Any] | None = None


@dataclass(frozen=True)
class GitBranchConfig:
    name: str | None
    base: str | None
    reuse: bool
    name_key: str | None = None
    name_template: str | None = None


@dataclass(frozen=True)
class GitCommitConfig:
    message_source: str | None
    message_key: str | None
    message_template: str | None = None


@dataclass(frozen=True)
class GitPushConfig:
    remote: str


@dataclass(frozen=True)
class GitPrConfig:
    base: str | None
    draft: bool
    title_key: str | None = None
    body_key: str | None = None
    title_template: str | None = None
    body_template: str | None = None
    number_key: str | None = None


@dataclass(frozen=True)
class PullRequestResult:
    url: str
    created: bool


@dataclass(frozen=True)
class GitConfig:
    branch: GitBranchConfig
    commit: GitCommitConfig
    push: GitPushConfig | None
    pr: GitPrConfig | None


@dataclass(frozen=True)
class SubTaskRouteConfig:
    when: dict[str, Any]
    goto: str | None = None
    continue_flow: bool = False


@dataclass(frozen=True)
class SubTaskConfig:
    task_id: str
    prompt_path: Path | None
    before: list[str]
    after: list[str]
    on_failure: list[str]
    when: str | None = None
    goto: str | None = None
    max_goto: int = 3
    wait_for_signal: str | None = None
    routes: list[SubTaskRouteConfig] = field(default_factory=list)
    must_set: list[str] = field(default_factory=list)


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
    signals: list[ExecutionSignalConfig]
    sub_tasks: list[SubTaskConfig]
    git: GitConfig | None
    agent: str | None = None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    on_failure: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PropagationTriggerConfig:
    after: str
    run: str
    on_signal: str | None
    when: dict[str, Any] | None = None
    # Context gate using sub-task `when` syntax: `:key` or `!:key`.
    when_context: str | None = None


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
    clone_dir: Path | None = None
    repo_cache_dir: Path | None = None


@dataclass(frozen=True)
class ActiveSignal:
    signal_type: str
    payload: dict[str, Any]
    source: str


@dataclass(frozen=True)
class RuntimeContext:
    agents: dict[str, str]
    default_agent: str
    context_sources: dict[str, ContextSourceConfig]
    active_signal: ActiveSignal | None
    initialized_signal_context_dirs: set[Path]
    signal_configs: dict[str, SignalConfig] = field(default_factory=dict)
    working_dir: Path = field(default_factory=Path)
    context_root: Path = field(default_factory=Path)
    config_dir: Path = field(default_factory=Path)
    execution_name: str = ""
    task_id: str = ""
    git_state: GitRunState | None = None
    signal_socket: zmq.Socket | None = None
    pub_socket: zmq.Socket | None = None
    metadata: dict = field(default_factory=dict)
    execution_agent: str | None = None


@dataclass
class PhaseStatus:
    before_completed: bool = False
    agent_completed: bool = False
    after_completed: bool = False


@dataclass
class TaskStatus:
    phases: PhaseStatus = field(default_factory=PhaseStatus)

    @property
    def is_completed(self) -> bool:
        return self.phases.after_completed


@dataclass
class ExecutionStatus:
    state: Literal["inactive", "pending", "in_progress", "completed"] = "inactive"
    tasks: dict[str, TaskStatus] = field(default_factory=dict)
    before_completed: bool = False
    after_completed: bool = False


@dataclass
class RunState:
    config_path: Path
    initial_execution: str
    executions: dict[str, ExecutionStatus]
    active_signal: ActiveSignal | None
    cloned_repos: dict[str, Path]
    initialized_signal_context_dirs: set[Path]
    # (after_exec, on_signal_or_None, run_exec)
    activated_triggers: set[tuple[str, str | None, str]] = field(default_factory=set)
    received_signal_types: set[str] = field(default_factory=set)
    # Opaque dict forwarded from the incoming ZMQ message to published events.
    # Telegram uses keys: chat_id, message_id (both str).
    metadata: dict = field(default_factory=dict)


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
