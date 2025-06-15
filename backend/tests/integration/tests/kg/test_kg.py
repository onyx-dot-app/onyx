import json
from datetime import datetime
from http import HTTPStatus

import pytest
import requests

from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import EntityType
from onyx.server.kg.models import KGConfig
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager


@pytest.mark.parametrize(
    "req, expected_status_code, expected_updated_config",
    [
        (
            EnableKGConfigRequest(
                vendor="Test",
                vendor_domains=["test.app", "tester.ai"],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
            HTTPStatus.OK,
            KGConfig(
                enabled=True,
                vendor="Test",
                vendor_domains=["test.app", "tester.ai"],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
        ),
        (
            EnableKGConfigRequest(
                vendor="Test",
                vendor_domains=[],
                ignore_domains=[],
                coverage_start=datetime(1970, 1, 1, 0, 0),
            ),
            HTTPStatus.BAD_REQUEST,
            None,
        ),
    ],
)
def test_kg_enable(
    reset: None,
    req: EnableKGConfigRequest,
    expected_status_code: int,
    expected_updated_config: KGConfig | None,
) -> None:
    admin_user = UserManager.create(name="admin_user")

    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        # Need to `.model_dump_json()` and then `json.loads`.
        # Seems redundant, but this is because simply calling `json=data.model_dump()`
        # returns in a "datetime cannot be JSON serialized error".
        json=json.loads(req.model_dump_json()),
    )
    assert res1.status_code == expected_status_code

    # We only check if the update has indeed been written to the DB iff the prior `PUT` was successful.
    if expected_status_code == HTTPStatus.OK:
        assert expected_updated_config

        res2 = requests.get(
            f"{API_SERVER_URL}/admin/kg/config",
            headers=admin_user.headers,
        )
        assert res2.status_code == HTTPStatus.OK

        actual_config = KGConfig.model_validate_json(res2.text)

        assert actual_config == expected_updated_config


@pytest.mark.parametrize(
    "req, expected_status_code",
    [
        (
            [
                EntityType(name="ACCOUNT", description="Test.", active=False),
                EntityType(name="CONCERN", description="Test 2.", active=True),
            ],
            HTTPStatus.OK,
        ),
        (
            [
                EntityType(name="NON-EXISTENT", description="Test.", active=False),
            ],
            HTTPStatus.BAD_REQUEST,
        ),
    ],
)
def test_kg_entity_type(
    reset: None,
    req: list[EntityType],
    expected_status_code: int,
) -> None:
    admin_user = UserManager.create(name="admin_user")

    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
        json=[entity_type.model_dump() for entity_type in req],
    )
    assert res1.status_code == expected_status_code

    if expected_status_code == HTTPStatus.OK:
        res2 = requests.get(
            f"{API_SERVER_URL}/admin/kg/entity-types",
            headers=admin_user.headers,
        )
        assert res2.status_code == HTTPStatus.OK

        req_map = {entity_type.name: entity_type for entity_type in req}

        entities: list = json.loads(res2.text)
        entity_types = [EntityType.model_validate_json(entity) for entity in entities]
        for et in entity_types:
            if et.name in req_map:
                assert et == req_map[et.name]
