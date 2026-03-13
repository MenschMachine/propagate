from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .constants import LOGGER
from .errors import PropagateError
from .models import RepositoryConfig


def clone_single_repository(name: str, repo: RepositoryConfig, existing_path: Path | None = None) -> Path:
    if existing_path is not None and existing_path.exists():
        LOGGER.info("Reusing existing clone for '%s' at '%s'.", name, existing_path)
        return existing_path
    clone_dir = Path(tempfile.mkdtemp(prefix="propagate-repo-"))
    LOGGER.info("Cloning repository '%s' from '%s' into '%s'.", name, repo.url, clone_dir)
    try:
        subprocess.run(
            ["git", "clone", repo.url, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(
            f"Failed to clone repository '{name}' from '{repo.url}': {error.stderr.strip()}"
        ) from error
    if repo.ref is not None:
        try:
            subprocess.run(
                ["git", "checkout", repo.ref],
                cwd=str(clone_dir),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            raise PropagateError(
                f"Failed to checkout ref '{repo.ref}' for repository '{name}': {error.stderr.strip()}"
            ) from error
    LOGGER.info("Cloned repository '%s' to '%s'.", name, clone_dir)
    return clone_dir
