import contextvars
import logging
import re

from propagate_app.log_buffer import install_buffered_handler

# Thread-safe context variable for project stem (set per-execution in coordinator)
_current_project_stem: contextvars.ContextVar[str] = contextvars.ContextVar("project_stem", default="")


def configure_logging(project_stem: str | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(project_stem)s] [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_buffered_handler()


class _ProjectStemLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that reads project_stem from context var."""

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        kwargs.setdefault("extra", {})["project_stem"] = _current_project_stem.get()
        return msg, kwargs


def set_project_stem(stem: str) -> contextvars.Token:
    """Set the project stem for the current execution context."""
    return _current_project_stem.set(stem)


LOGGER = _ProjectStemLoggerAdapter(logging.getLogger("propagate"), {})
CONTEXT_KEY_PATTERN = re.compile(r"^:?[A-Za-z0-9][A-Za-z0-9._-]*$")
CONTEXT_SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SIGNAL_NAMESPACE_PREFIX = ":signal"
SUPPORTED_SIGNAL_FIELD_TYPES = {"string", "number", "boolean", "list", "mapping", "any"}

ENV_CONTEXT_ROOT = "PROPAGATE_CONTEXT_ROOT"
ENV_CONFIG_DIR = "PROPAGATE_CONFIG_DIR"
ENV_CLONE_DIR = "PROPAGATE_CLONE_DIR"
ENV_EXECUTION = "PROPAGATE_EXECUTION"
ENV_TASK = "PROPAGATE_TASK"

CLONE_DIR_PREFIX = ""
CLONE_MARKER_FILENAME = ".propagate-clone"
BARE_CLONE_MARKER_FILENAME = "propagate-bare-clone"

PHASE_BEFORE = "before"
PHASE_AGENT = "agent"
PHASE_AFTER = "after"
