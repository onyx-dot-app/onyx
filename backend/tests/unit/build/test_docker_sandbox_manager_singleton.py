from unittest.mock import patch

import pytest

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    DockerSandboxManager,
)


def test_failed_initialize_does_not_poison_singleton() -> None:
    """A failed ``_initialize()`` must not cache a half-built singleton: ``__new__``
    publishes to the class cache only after init succeeds, and a later construction
    retries once the transient condition clears."""
    DockerSandboxManager._instance = None
    try:
        attempts = {"count": 0}

        def flaky_initialize(_self: DockerSandboxManager) -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient docker socket failure")
            # second attempt succeeds (no-op)

        with patch.object(DockerSandboxManager, "_initialize", flaky_initialize):
            with pytest.raises(RuntimeError, match="transient docker socket failure"):
                DockerSandboxManager()

            # failed init left nothing cached
            assert DockerSandboxManager._instance is None

            # next construction retries and becomes the cached instance
            manager = DockerSandboxManager()
            assert manager is DockerSandboxManager._instance
            assert attempts["count"] == 2
    finally:
        DockerSandboxManager._instance = None
