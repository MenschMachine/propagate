from __future__ import annotations

import fcntl
import os
import re
import subprocess
import tempfile
from pathlib import Path
from tempfile import mkdtemp

from .constants import BARE_CLONE_MARKER_FILENAME, CLONE_DIR_PREFIX, CLONE_MARKER_FILENAME, ENV_CLONE_DIR, LOGGER
from .errors import PropagateError
from .models import RepositoryConfig

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+)$")
_HTTPS_RE = re.compile(r"^https://([^@/]+@)?(.+)$")
_CLONE_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _ssh_url_to_https(url: str) -> str:
    """Convert an SSH git URL to HTTPS.  Non-SSH URLs pass through unchanged."""
    m = _SSH_URL_RE.match(url)
    if m is None:
        return url
    host = m.group(1)
    path = m.group(2)
    return f"https://{host}/{path}"


def _inject_token_into_url(url: str, token: str | None) -> str:
    """Inject a GitHub token into an HTTPS URL for authentication.

    Returns the URL unchanged when *token* is empty/None, the URL is not HTTPS,
    or the URL already contains credentials.
    """
    if not token or not url.startswith("https://"):
        return url
    m = _HTTPS_RE.match(url)
    if m is None:
        return url
    # Already has credentials (user:pass@ or user@)
    if m.group(1) is not None:
        return url
    rest = m.group(2)
    return f"https://x-access-token:{token}@{rest}"


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
    return path.is_dir() and (path / CLONE_MARKER_FILENAME).is_file()


def _sanitize_clone_name(value: str) -> str:
    sanitized = _CLONE_NAME_SANITIZE_RE.sub("-", value).strip("-.")
    return sanitized


def _clone_dir_prefix(project_name: str | None, repo_name: str) -> str:
    parts: list[str] = []
    if project_name:
        sanitized_project = _sanitize_clone_name(project_name)
        if sanitized_project:
            parts.append(sanitized_project)
    sanitized_repo = _sanitize_clone_name(repo_name)
    if sanitized_repo:
        parts.append(sanitized_repo)
    if not parts:
        return "repo-"
    return f"{CLONE_DIR_PREFIX}{'-'.join(parts)}-"


def _write_clone_marker(repo_dir: Path) -> None:
    marker_path = repo_dir / CLONE_MARKER_FILENAME
    marker_path.write_text("", encoding="utf-8")


def _add_clone_marker_to_local_exclude(repo_dir: Path) -> None:
    exclude_path = repo_dir / ".git" / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if exclude_path.exists():
        existing = exclude_path.read_text(encoding="utf-8")
        if any(line.strip() == CLONE_MARKER_FILENAME for line in existing.splitlines()):
            return

    prefix = ""
    if existing and not existing.endswith("\n"):
        prefix = "\n"
    exclude_path.write_text(f"{existing}{prefix}{CLONE_MARKER_FILENAME}\n", encoding="utf-8")


def _bare_cache_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / f"{_sanitize_clone_name(name)}.git"


def is_propagate_bare_cache(path: Path) -> bool:
    return path.is_dir() and (path / BARE_CLONE_MARKER_FILENAME).is_file()


def _ensure_bare_cache(
    name: str,
    repo: RepositoryConfig,
    cache_dir: Path,
    effective_dir: Path | None,
) -> Path:
    """Create or refresh the bare repo cache and return a fresh local clone dir."""
    bare_path = _bare_cache_path(cache_dir, name)
    lock_path = cache_dir / f"{_sanitize_clone_name(name)}.lock"
    token = os.environ.get("GITHUB_TOKEN")
    auth_url = _inject_token_into_url(_ssh_url_to_https(repo.url), token)
    clean_url = _ssh_url_to_https(repo.url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            if is_propagate_bare_cache(bare_path):
                LOGGER.debug("Refreshing bare cache for '%s'.", name)
                subprocess.run(
                    ["git", "remote", "set-url", "origin", auth_url],
                    cwd=str(bare_path), check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=str(bare_path), check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "remote", "set-url", "origin", clean_url],
                    cwd=str(bare_path), check=True, capture_output=True, text=True,
                )
            else:
                LOGGER.debug("Creating bare cache for '%s'.", name)
                try:
                    subprocess.run(
                        ["git", "clone", "--bare", auth_url, str(bare_path)],
                        check=True, capture_output=True, text=True,
                    )
                except subprocess.CalledProcessError as error:
                    raise PropagateError(
                        f"Failed to create bare cache for '{name}' from '{clean_url}': {error.stderr.strip()}"
                    ) from error
                bare_path.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["git", "remote", "set-url", "origin", clean_url],
                    cwd=str(bare_path), check=True, capture_output=True, text=True,
                )
                (bare_path / BARE_CLONE_MARKER_FILENAME).write_text("", encoding="utf-8")
            dest_dir = Path(mkdtemp(prefix=_clone_dir_prefix(None, name), dir=effective_dir))
            try:
                subprocess.run(
                    ["git", "clone", str(bare_path), str(dest_dir)],
                    check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as error:
                raise PropagateError(
                    f"Failed to clone from bare cache for '{name}': {error.stderr.strip()}"
                ) from error
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    return dest_dir


def clone_single_repository(
    name: str,
    repo: RepositoryConfig,
    existing_path: Path | None = None,
    clone_dir: Path | None = None,
    project_name: str | None = None,
    repo_cache_dir: Path | None = None,
) -> Path:
    if existing_path is not None and existing_path.exists():
        LOGGER.info("Reusing existing clone for '%s' at '%s'.", name, existing_path)
        _configure_credential_helper(existing_path)
        return existing_path
    clone_url = _ssh_url_to_https(repo.url)
    token = os.environ.get("GITHUB_TOKEN")
    auth_url = _inject_token_into_url(clone_url, token)
    env_clone_dir = os.environ.get(ENV_CLONE_DIR)
    effective_dir = Path(env_clone_dir) if env_clone_dir else clone_dir
    if repo_cache_dir is not None and env_clone_dir is None:
        dest_dir = _ensure_bare_cache(name, repo, repo_cache_dir, effective_dir)
        subprocess.run(
            ["git", "remote", "set-url", "origin", clone_url],
            cwd=str(dest_dir), check=True, capture_output=True, text=True,
        )
        if repo.ref is not None:
            try:
                subprocess.run(
                    ["git", "checkout", repo.ref],
                    cwd=str(dest_dir), check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as error:
                raise PropagateError(
                    f"Failed to checkout ref '{repo.ref}' for repository '{name}': {error.stderr.strip()}"
                ) from error
        try:
            _write_clone_marker(dest_dir)
            _add_clone_marker_to_local_exclude(dest_dir)
        except OSError as error:
            raise PropagateError(f"Failed to mark clone directory '{dest_dir}': {error}") from error
        _configure_credential_helper(dest_dir)
        LOGGER.info("Cloned repository '%s' from cache to '%s'.", name, dest_dir)
        return dest_dir
    if effective_dir is not None:
        try:
            effective_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PropagateError(f"Cannot create clone directory '{effective_dir}': {error}") from error
    dest_dir = Path(tempfile.mkdtemp(prefix=_clone_dir_prefix(project_name, name), dir=effective_dir))
    LOGGER.info("Cloning repository '%s' from '%s' into '%s'.", name, clone_url, dest_dir)
    try:
        subprocess.run(
            ["git", "clone", auth_url, str(dest_dir)],
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
    try:
        _write_clone_marker(dest_dir)
        _add_clone_marker_to_local_exclude(dest_dir)
    except OSError as error:
        raise PropagateError(f"Failed to mark clone directory '{dest_dir}': {error}") from error
    _configure_credential_helper(dest_dir)
    LOGGER.info("Cloned repository '%s' to '%s'.", name, dest_dir)
    return dest_dir
