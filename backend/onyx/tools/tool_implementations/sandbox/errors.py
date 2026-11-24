"""The tool errors of the sandbox tools and the artifact operations."""

from collections.abc import Iterator
from contextlib import contextmanager

from onyx.server.features.build.sandbox.harness_base import HarnessSandboxError
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.sandbox.models import (
    ArtifactNotFound,
    ArtifactVersionConflict,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def tool_error(message: str) -> ToolCallException:
    return ToolCallException(message, message)


@contextmanager
def sandbox_errors_as_tool_errors() -> Iterator[None]:
    """Sandbox errors that the model can act on become tool errors with their
    message."""
    try:
        yield
    except HarnessSandboxError as error:
        raise tool_error(str(error)) from error


@contextmanager
def artifact_errors(action: str) -> Iterator[None]:
    """The tool errors of an artifact operation's `action` ("The copy"): a
    tool error as it is, a sandbox error's or a missing artifact's own
    message, or a fixed one; the details go to the log. A version conflict
    passes, for each tool to word."""
    try:
        yield
    except (ToolCallException, ArtifactVersionConflict):
        raise
    except (HarnessSandboxError, ArtifactNotFound) as error:
        raise tool_error(str(error)) from error
    except TimeoutError as error:
        logger.warning("artifact_tool_timed_out action=%s", action, exc_info=True)
        raise tool_error(f"{action} timed out; try again") from error
    except Exception as error:
        logger.exception("artifact_tool_failed action=%s", action)
        raise tool_error(f"{action} failed; try again") from error
