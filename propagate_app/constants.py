import logging
import re

from propagate_app.log_buffer import install_buffered_handler


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_buffered_handler()


LOGGER = logging.getLogger("propagate")
CONTEXT_KEY_PATTERN = re.compile(r"^:?[A-Za-z0-9][A-Za-z0-9._-]*$")
CONTEXT_SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SIGNAL_NAMESPACE_PREFIX = ":signal"
SUPPORTED_SIGNAL_FIELD_TYPES = {"string", "number", "boolean", "list", "mapping", "any"}

ENV_CONTEXT_ROOT = "PROPAGATE_CONTEXT_ROOT"
ENV_CONFIG_DIR = "PROPAGATE_CONFIG_DIR"
ENV_EXECUTION = "PROPAGATE_EXECUTION"
ENV_TASK = "PROPAGATE_TASK"

CLONE_DIR_PREFIX = "propagate-repo-"

PHASE_BEFORE = "before"
PHASE_AGENT = "agent"
PHASE_AFTER = "after"
