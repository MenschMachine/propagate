import tempfile
from pathlib import Path

from .constants import LOGGER
from .errors import PropagateError


def write_temp_text(content: str, prefix: str, suffix: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as handle:
            handle.write(content)
    except OSError as error:
        raise PropagateError(f"Failed to write temporary file: {error}") from error
    return Path(handle.name)


def cleanup_temp_file(temp_path: Path, label: str) -> None:
    try:
        temp_path.unlink(missing_ok=True)
    except OSError as error:
        LOGGER.warning("Failed to remove %s '%s': %s", label, temp_path, error)
