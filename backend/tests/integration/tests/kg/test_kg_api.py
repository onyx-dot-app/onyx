import json
from datetime import datetime
from http import HTTPStatus

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import set_kg_config_settings
from onyx.db.models import Connector
from onyx.server.documents.models import ConnectorBase
from onyx.server.kg.models import DisableKGConfigRequest
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import EntityType
from onyx.server.kg.models import KGConfig as KGConfigAPIModel
from onyx.server.kg.models import SourceAndEntityTypeView
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all


@pytest.fixture(autouse=True)
def reset_for_test() -> None:
    """Reset all data before each test."""
    reset_all()

    kg_config_settings = get_kg_config_settings()
    kg_config_settings.KG_EXPOSED = True
    set_kg_config_settings(kg_config_settings)


@pytest.fixture()
def connectors() -> None:
    """Set up connectors for tests."""
    with get_session_with_current_tenant() as db_session:
        # Create Salesforce connector
        connector_data = ConnectorBase(
            name="Salesforce Test",
            source=DocumentSource.SALESFORCE,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=None,
            indexing_start=None,
            prune_freq=None,
        )
        create_connector(db_session, connector_data)


def test_kg_enable_and_disable() -> None:
    admin_user = UserManager.create(name="admin_user")

    # Enable KG
    # Need to `.model_dump_json()` and then `json.loads`.
    # Seems redundant, but this is because simply calling `json=data.model_dump()`
    # returns in a "datetime cannot be JSON serialized error".
    req1 = json.loads(
        EnableKGConfigRequest(
            vendor="Test",
            vendor_domains=["test.app", "tester.ai"],
            ignore_domains=[],
            coverage_start=datetime(1970, 1, 1, 0, 0),
        ).model_dump_json()
    )
    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        json=req1,
    )
    assert (
        res1.status_code == HTTPStatus.OK
    ), f"Error response: {res1.status_code} - {res1.text}"

    # Check KG
    res2 = requests.get(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
    )
    assert (
        res2.status_code == HTTPStatus.OK
    ), f"Error response: {res2.status_code} - {res2.text}"

    actual_config = KGConfigAPIModel.model_validate_json(res2.text)
    assert actual_config == KGConfigAPIModel(
        enabled=True,
        vendor="Test",
        vendor_domains=["test.app", "tester.ai"],
        ignore_domains=[],
        coverage_start=datetime(1970, 1, 1, 0, 0),
    )

    # Disable KG
    req3 = DisableKGConfigRequest().model_dump()
    res3 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        json=req3,
    )
    assert (
        res3.status_code == HTTPStatus.OK
    ), f"Error response: {res3.status_code} - {res3.text}"

    # Check KG
    res4 = requests.get(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
    )
    assert (
        res4.status_code == HTTPStatus.OK
    ), f"Error response: {res4.status_code} - {res4.text}"

    actual_config = KGConfigAPIModel.model_validate_json(res4.text)
    assert actual_config == KGConfigAPIModel(
        enabled=False,
        vendor="Test",
        vendor_domains=["test.app", "tester.ai"],
        ignore_domains=[],
        coverage_start=datetime(1970, 1, 1, 0, 0),
    )


def test_kg_enable_with_missing_fields_should_fail() -> None:
    admin_user = UserManager.create(name="admin_user")

    req = json.loads(
        EnableKGConfigRequest(
            vendor="Test",
            vendor_domains=[],
            ignore_domains=[],
            coverage_start=datetime(1970, 1, 1, 0, 0),
        ).model_dump_json()
    )
    res = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        json=req,
    )
    assert res.status_code == HTTPStatus.BAD_REQUEST


def test_update_kg_entity_types(connectors: None) -> None:
    admin_user = UserManager.create(name="admin_user")

    # Enable kg and populate default entity types
    req1 = json.loads(
        EnableKGConfigRequest(
            vendor="Test",
            vendor_domains=["test.app", "tester.ai"],
            ignore_domains=[],
            coverage_start=datetime(1970, 1, 1, 0, 0),
        ).model_dump_json()
    )
    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        json=req1,
    )
    assert (
        res1.status_code == HTTPStatus.OK
    ), f"Error response: {res1.status_code} - {res1.text}"

    # Get old entity types
    res2 = requests.get(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
    )
    assert (
        res2.status_code == HTTPStatus.OK
    ), f"Error response: {res2.status_code} - {res2.text}"
    res2_parsed = SourceAndEntityTypeView.model_validate(res2.json())

    # Update entity types
    req3 = [
        EntityType(
            name="ACCOUNT",
            description="Test.",
            active=True,
            grounded_source_name="salesforce",
        ).model_dump(),
        EntityType(
            name="OPPORTUNITY",
            description="Test 2.",
            active=False,
        ).model_dump(),
    ]
    res3 = requests.put(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
        json=req3,
    )
    assert (
        res3.status_code == HTTPStatus.OK
    ), f"Error response: {res3.status_code} - {res3.text}"

    # Check connector kg_processing is enabled
    with get_session_with_current_tenant() as db_session:
        connector = (
            db_session.query(Connector)
            .filter(Connector.name == "Salesforce Test")
            .scalar()
        )
        assert connector.kg_processing_enabled

    # Check entity types looks correct
    res4 = requests.get(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
    )
    assert (
        res4.status_code == HTTPStatus.OK
    ), f"Error response: {res4.status_code} - {res4.text}"
    res4_parsed = SourceAndEntityTypeView.model_validate(res4.json())

    def to_entity_type_map(map: dict[str, list[EntityType]]) -> dict[str, EntityType]:
        return {
            entity_type.name: entity_type
            for entity_types in map.values()
            for entity_type in entity_types
        }

    expected_entity_types = to_entity_type_map(map=res2_parsed.entity_types)
    new_entity_types = to_entity_type_map(map=res4_parsed.entity_types)

    # These are the updates.
    # We're just manually updating them.
    expected_entity_types["ACCOUNT"].active = True
    expected_entity_types["ACCOUNT"].description = "Test."
    expected_entity_types["OPPORTUNITY"].active = False
    expected_entity_types["OPPORTUNITY"].description = "Test 2."

    assert new_entity_types == expected_entity_types


def test_update_invalid_kg_entity_type_should_do_nothing(connectors: None) -> None:
    admin_user = UserManager.create(name="admin_user")

    # Enable kg and populate default entity types
    req1 = json.loads(
        EnableKGConfigRequest(
            vendor="Test",
            vendor_domains=["test.app", "tester.ai"],
            ignore_domains=[],
            coverage_start=datetime(1970, 1, 1, 0, 0),
        ).model_dump_json()
    )
    res1 = requests.put(
        f"{API_SERVER_URL}/admin/kg/config",
        headers=admin_user.headers,
        json=req1,
    )
    assert (
        res1.status_code == HTTPStatus.OK
    ), f"Error response: {res1.status_code} - {res1.text}"

    # Get old entity types
    res2 = requests.get(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
    )
    assert (
        res2.status_code == HTTPStatus.OK
    ), f"Error response: {res2.status_code} - {res2.text}"

    # Update entity types with non-existent entity type
    req3 = [
        EntityType(name="NON-EXISTENT", description="Test.", active=False).model_dump(),
    ]
    res3 = requests.put(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
        json=req3,
    )
    assert (
        res3.status_code == HTTPStatus.OK
    ), f"Error response: {res3.status_code} - {res3.text}"

    # Get entity types after the update attempt
    res4 = requests.get(
        f"{API_SERVER_URL}/admin/kg/entity-types",
        headers=admin_user.headers,
    )
    assert (
        res4.status_code == HTTPStatus.OK
    ), f"Error response: {res4.status_code} - {res4.text}"

    # Should be the same as before since non-existent entity type should be ignored
    assert res2.json() == res4.json()
