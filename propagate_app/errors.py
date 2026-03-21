class PropagateError(Exception):
    """Raised when the CLI encounters a user-facing error."""


class UnableToImplementError(PropagateError):
    """Raised when a task determines it cannot complete the requested implementation."""


def build_named_error(kind: str, message: str) -> PropagateError:
    normalized_kind = kind.strip().lower().replace("_", "-")
    if normalized_kind == "unable-to-implement":
        return UnableToImplementError(message)
    raise PropagateError(
        f"Unknown failure kind '{kind}'. Supported kinds: unable-to-implement."
    )


def wrap_error_with_message(err: PropagateError, message: str) -> PropagateError:
    if isinstance(err, UnableToImplementError):
        exc = UnableToImplementError(message)
    else:
        exc = PropagateError(message)
    exc.__cause__ = err
    return exc
