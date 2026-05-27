"""HTTP client for the long-lived ``opencode serve`` process inside the
sandbox pod.

Replaces the ephemeral-per-message ``opencode acp`` exec clients
(``sandbox/acp/``, ``sandbox/kubernetes/internal/acp_exec_client.py``,
``sandbox/docker/internal/acp_exec_client.py``) post-Phase-5 of the
migration documented in ``docs/craft/opencode-serve-migration.md``.

Public surface: :class:`OpencodeServeClient`.
"""

from onyx.server.features.build.sandbox.opencode.serve_client import ClientTimeouts
from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient

__all__ = ["OpencodeServeClient", "ClientTimeouts"]
