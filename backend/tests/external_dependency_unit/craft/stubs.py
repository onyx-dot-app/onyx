"""Re-exports the canonical StubSandboxManager from the shared location.

The canonical implementation lives in ``tests/common/craft/stubs.py`` so
both ``external_dependency_unit`` and ``unit`` test layers can import the
same stub without crossing layer boundaries inappropriately.
"""

from tests.common.craft.stubs import StubSandboxManager  # noqa: F401
