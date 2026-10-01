"""Opt-in gates for the suites under ``backend/tests/manual``.

Manual suites spend money, download large model weights or change a live
deployment, so they never run by default. Each suite declares its gate env
vars with :func:`manual_suite`. The suite runs only when every gate env var is
``true``. Nothing here reads a secret store: keys come from plain env vars.
"""

import os

import pytest

CLOUD_EMBEDDING_GATE = "ONYX_RUN_CLOUD_EMBEDDING_TESTS"
SELF_HOSTED_EMBEDDING_GATE = "ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS"
EMBEDDING_E2E_GATE = "ONYX_EMBEDDING_E2E"
EMBEDDING_E2E_MUTATION_GATE = "ONYX_EMBEDDING_E2E_ALLOW_MUTATION"

MANUAL_SUITE_MARKER = "manual_suite"

README_PATH = "backend/tests/manual/embedding_models/README.md"

_TRUE_VALUES = frozenset({"true", "1"})


def env_flag(name: str) -> bool:
    """True if the env var is set to ``true`` or ``1`` (case-insensitive)."""
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def missing_gates(env_vars: tuple[str, ...]) -> list[str]:
    """The gate env vars that are not set to true."""
    return [name for name in env_vars if not env_flag(name)]


def skip_reason(missing: list[str]) -> str:
    settings = " and ".join(f"{name}=true" for name in missing)
    return f"Manual suite. Set {settings} to run it. See {README_PATH}."


def manual_suite(*env_vars: str) -> list[pytest.MarkDecorator]:
    """The ``pytestmark`` for a manual suite module.

    The ``manual_suite`` marker tells ``tests/manual/conftest.py`` which gates
    to check. The ``skipif`` repeats the check in the module itself, so the
    suite stays skipped even when pytest runs with ``--noconftest``.
    """
    if not env_vars:
        raise ValueError("A manual suite needs at least one gate env var.")
    missing = missing_gates(env_vars)
    return [
        pytest.mark.manual_suite(*env_vars),
        pytest.mark.skipif(bool(missing), reason=skip_reason(missing)),
    ]
