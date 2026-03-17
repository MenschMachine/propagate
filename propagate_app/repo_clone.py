from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .constants import CLONE_DIR_PREFIX, ENV_CLONE_DIR, LOGGER
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


def clone_single_repository(
    name: str, repo: RepositoryConfig, existing_path: Path | None = None, clone_dir: Path | None = None
) -> Path:
    if existing_path is not None and existing_path.exists():
        LOGGER.info("Reusing existing clone for '%s' at '%s'.", name, existing_path)
        _configure_credential_helper(existing_path)
        return existing_path
    clone_url = _ssh_url_to_https(repo.url)
    env_clone_dir = os.environ.get(ENV_CLONE_DIR)
    effective_dir = Path(env_clone_dir) if env_clone_dir else clone_dir
    if effective_dir is not None:
        try:
            effective_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PropagateError(f"Cannot create clone directory '{effective_dir}': {error}") from error
    dest_dir = Path(tempfile.mkdtemp(prefix=CLONE_DIR_PREFIX, dir=effective_dir))
    LOGGER.info("Cloning repository '%s' from '%s' into '%s'.", name, clone_url, dest_dir)
    try:
        subprocess.run(
            ["git", "clone", clone_url, str(dest_dir)],
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
                cwd=str(dest_dir),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            raise PropagateError(
                f"Failed to checkout ref '{repo.ref}' for repository '{name}': {error.stderr.strip()}"
            ) from error
    _configure_credential_helper(dest_dir)
    LOGGER.info("Cloned repository '%s' to '%s'.", name, dest_dir)
    return dest_dir
