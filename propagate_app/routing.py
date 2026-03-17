from .constants import LOGGER
from .context_store import get_context_root
from .errors import PropagateError
from .models import Config, ExecutionConfig, ExecutionRouting, RuntimeContext
from .signal_context import prepare_signal_context_for_working_dir


def prepare_execution_runtime_context(
    config: Config,
    execution: ExecutionConfig,
    runtime_context: RuntimeContext,
) -> RuntimeContext:
    routing = resolve_execution_routing(execution, config)
    log_execution_routing(execution, routing)
    ensure_execution_working_dir(execution, routing)
    context_root = get_context_root(config.config_path)
    execution_runtime_context = RuntimeContext(
        agent_command=runtime_context.agent_command,
        context_sources=runtime_context.context_sources,
        working_dir=routing.working_dir,
        active_signal=runtime_context.active_signal,
        initialized_signal_context_dirs=runtime_context.initialized_signal_context_dirs,
        context_root=context_root,
        config_dir=runtime_context.config_dir,
        execution_name=execution.name,
        signal_socket=runtime_context.signal_socket,
    )
    prepare_signal_context_for_working_dir(execution_runtime_context)
    return execution_runtime_context


def resolve_execution_routing(execution: ExecutionConfig, config: Config) -> ExecutionRouting:
    repo = config.repositories[execution.repository]
    if repo.path is None:
        raise PropagateError(
            f"Execution '{execution.name}' references repository '{execution.repository}' which has no resolved path."
        )
    return ExecutionRouting(
        working_dir=repo.path,
        location_display=execution_location_display(execution),
        repository_name=execution.repository,
    )


def log_execution_routing(execution: ExecutionConfig, routing: ExecutionRouting) -> None:
    LOGGER.info(
        "Routing execution '%s' to repository '%s' at '%s'.",
        execution.name,
        routing.repository_name,
        routing.working_dir,
    )


def ensure_execution_working_dir(execution: ExecutionConfig, routing: ExecutionRouting) -> None:
    if not routing.working_dir.exists():
        raise PropagateError(
            f"Execution '{execution.name}' cannot start {routing.location_display}: working directory does not exist: {routing.working_dir}"
        )
    if not routing.working_dir.is_dir():
        raise PropagateError(
            f"Execution '{execution.name}' cannot start {routing.location_display}: working directory is not a directory: {routing.working_dir}"
        )


def execution_location_display(execution: ExecutionConfig) -> str:
    return f"in repository '{execution.repository}'"


def wrap_execution_runtime_error(execution: ExecutionConfig, error: PropagateError) -> PropagateError:
    return PropagateError(
        f"Execution '{execution.name}' failed while running {execution_location_display(execution)}: {normalize_error_message(str(error))}."
    )


def normalize_error_message(message: str) -> str:
    return message.rstrip().rstrip(".")
