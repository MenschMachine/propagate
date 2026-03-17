from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .constants import CLONE_DIR_PREFIX, LOGGER
from .errors import PropagateError
from .models import RepositoryConfig

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+)$")


def _ssh_url_to_https(url: str) -> str:
    """Convert an SSH git URL to HTTPS.  Non-SSH URLs pass through unchanged."""
    m = _SSH_URL_RE.match(url)
    if m is None:
        return url
    host = m.group(1)
    path = m.group(2)
    return f"https://{host}/{path}"


def _configure_credential_helper(repo_dir: Path) -> None:
    """Set the local git credential helper to use ``gh auth git-credential``."""
    subprocess.run(
        ["git", "config", "credential.helper", "!gh auth git-credential"],
        cwd=str(repo_dir),
        check=True,
        capture_output=True,
        text=True,
    )
    LOGGER.debug("Configured gh credential helper for '%s'.", repo_dir)


def is_propagate_clone(path: Path) -> bool:
    """Check whether *path* looks like a propagate-created clone directory."""
    return path.is_dir() and path.name.startswith(CLONE_DIR_PREFIX)


def clone_single_repository(name: str, repo: RepositoryConfig, existing_path: Path | None = None) -> Path:
    if existing_path is not None and existing_path.exists():
        LOGGER.info("Reusing existing clone for '%s' at '%s'.", name, existing_path)
        _configure_credential_helper(existing_path)
        return existing_path
    clone_url = _ssh_url_to_https(repo.url)
    clone_dir = Path(tempfile.mkdtemp(prefix=CLONE_DIR_PREFIX))
    LOGGER.info("Cloning repository '%s' from '%s' into '%s'.", name, clone_url, clone_dir)
    try:
        subprocess.run(
            ["git", "clone", clone_url, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise PropagateError(
            f"Failed to clone repository '{name}' from '{clone_url}': {error.stderr.strip()}"
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
    _configure_credential_helper(clone_dir)
    LOGGER.info("Cloned repository '%s' to '%s'.", name, clone_dir)
    return clone_dir
