from __future__ import annotations

import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from .constants import LOGGER
from .errors import PropagateError
from .models import Config, RepositoryConfig


def clone_url_repositories(config: Config) -> Config:
    updated_repos: dict[str, RepositoryConfig] = {}
    for name, repo in config.repositories.items():
        if repo.url is None:
            updated_repos[name] = repo
            continue
        clone_dir = Path(tempfile.mkdtemp(prefix="propagate-repo-"))
        LOGGER.debug("Cloning '%s' from '%s' into '%s'.", name, repo.url, clone_dir)
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
        updated_repos[name] = replace(repo, path=clone_dir)
    return replace(config, repositories=updated_repos)
