"""Reuses the permissions package fixtures.

These directories exist only so CI shards them as separate jobs — the suite is
one logical package split for wall-clock, and `find -maxdepth 1` in
pr-integration-tests.yml only sees immediate children of tests/.
"""

from tests.integration.tests.permissions.conftest import *  # noqa: F401,F403

# `import *` skips underscore names, and these two are fixtures other tests request.
from tests.integration.tests.permissions.conftest import (  # noqa: F401
    _attach_group_with_permission,
    _scoped_setup,
)
