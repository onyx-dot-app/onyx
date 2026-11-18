from functools import partial

import pytest
from alembic.config import Config as AlembicConfig
from pytest_alembic.config import Config
from pytest_alembic.tests import (
    test_model_definitions_match_ddl,
    test_single_head_revision,
    test_up_down_consistency,
    test_upgrade,
)

from tests.integration.tests.migrations.ddl_baseline import exclude_known_drift
from tests.integration.tests.migrations.revision_roundtrip import (
    test_each_revision_round_trip,
)


@pytest.fixture
def alembic_config() -> Config:
    return Config(
        config_options={
            "process_revision_directives": partial(
                exclude_known_drift, chain="alembic_tenants"
            )
        },
        alembic_config=AlembicConfig("alembic.ini", ini_section="schema_private"),
    )


__all__ = [
    "test_each_revision_round_trip",
    "test_model_definitions_match_ddl",
    "test_single_head_revision",
    "test_up_down_consistency",
    "test_upgrade",
]
