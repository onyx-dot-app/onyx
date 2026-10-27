"""Use the deployed API; leave host services and other sandboxes untouched."""

from tests.common.craft.deployment_fixtures import (
    _module_reset_and_seed as _module_reset_and_seed,
)
from tests.common.craft.deployment_fixtures import (
    _reap_module_sandboxes as _reap_module_sandboxes,
)
from tests.common.craft.deployment_fixtures import (
    _run_migrations as _run_migrations,
)
from tests.common.craft.deployment_fixtures import (
    _start_celery_workers as _start_celery_workers,
)
from tests.common.craft.deployment_fixtures import (
    _test_client as _test_client,
)
from tests.common.craft.deployment_fixtures import (
    deployed_frontend as deployed_frontend,
)
from tests.common.craft.deployment_fixtures import (
    initialize_db as initialize_db,
)
from tests.common.craft.deployment_fixtures import (
    seed_dev_license_for_session as seed_dev_license_for_session,
)
