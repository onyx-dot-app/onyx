import time

import pytest

from onyx.background.celery.tasks.kg_processing.kg_indexing import (
    try_creating_kg_processing_task,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_processing_blocked,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import set_kg_config_settings
from onyx.db.models import Connector
from onyx.db.models import Document
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGStage
from onyx.kg.models import KGAttributeEntityOption
from onyx.kg.models import KGAttributeImplicationProperty
from onyx.kg.models import KGAttributeProperty
from onyx.kg.models import KGAttributeTrackInfo
from onyx.kg.models import KGAttributeTrackType
from onyx.kg.models import KGEntityTypeAttributes
from onyx.kg.models import KGEntityTypeDefinition
from onyx.kg.models import KGGroundingType
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def reset_for_test() -> None:
    """Reset all data before each test."""
    reset_all()

    kg_config_settings = get_kg_config_settings()
    kg_config_settings.KG_EXPOSED = True
    kg_config_settings.KG_ENABLED = True
    kg_config_settings.KG_VENDOR = "Test"
    kg_config_settings.KG_VENDOR_DOMAINS = ["onyx-test.com.app", "tester.ai"]
    kg_config_settings.KG_IGNORE_EMAIL_DOMAINS = ["gmail.com"]
    kg_config_settings.KG_COVERAGE_START = "2020-01-01"
    set_kg_config_settings(kg_config_settings)


@pytest.fixture()
def kg_test_docs() -> tuple[list[str], int, list[KGEntityType]]:

    # create admin user
    admin_user: DATestUser = UserManager.create(email="admin@onyx-test.com.app")

    # create a minimal file connector
    cc_pair = CCPairManager.create_from_scratch(
        name="KG-Test-FileConnector",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [],
            "file_names": [],
            "zip_metadata": {},
        },
        user_performing_action=admin_user,
    )
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    api_key.headers.update(admin_user.headers)
    LLMProviderManager.create(user_performing_action=admin_user)

    # create test document
    # semantic id = Test Document {document_id}
    # source type = FILE
    doc1 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content for KG doc A",
        document_id="docA",
        metadata={
            "teamname": "Team1",
            "assignees": ["john@gmail.com", "dane@tester.ai"],
            "parent": "Test Document docB",
            "key": "Test Document docA",
            "stuff": ["a", "b", "c", "d", "e", "f", "g"],
        },
        api_key=api_key,
    )
    doc2 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair,
        content="Dummy content for KG doc BS",
        document_id="docB",
        metadata={
            "teamname": "Team2",
            "assignees": ["david@outsider.com"],
            "key": "Test Document docB",
            "stuff": ["h", "i", "j", "k", "l", "m", "n"],
        },
        api_key=api_key,
    )

    # create entity type
    entity_type_definitions = {
        "TEST": KGEntityTypeDefinition(
            description="A test entity",
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "teamname": KGAttributeProperty(name="team", keep=True),
                    "stuff": KGAttributeProperty(name="stuff", keep=True),
                    "assignees": KGAttributeProperty(
                        name="assignees",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_assignee_of",
                        ),
                    ),
                    "parent": KGAttributeProperty(
                        name="parent",  # will also create has_subcomponent
                        keep=True,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type="TEST",
                            implied_relationship_name="is_parent_of",
                        ),
                    ),
                    "key": KGAttributeProperty(name="key", keep=True),
                },
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.FILE,
            active=True,
        ),
        "ACCOUNT": KGEntityTypeDefinition(
            description=("A company"),
            attributes=KGEntityTypeAttributes(
                entity_filter_attributes={"object_type": "Account"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SALESFORCE,
            active=True,
        ),
        "EMPLOYEE": KGEntityTypeDefinition(
            description="An employee",
            grounding=KGGroundingType.GROUNDED,
            active=True,
            grounded_source_name=None,
        ),
    }

    kg_entity_types: list[KGEntityType] = []
    with get_session_with_current_tenant() as db_session:
        for (
            entity_type_id_name,
            entity_type_definition,
        ) in entity_type_definitions.items():
            grounded_source_name = (
                entity_type_definition.grounded_source_name.value
                if entity_type_definition.grounded_source_name
                else None
            )
            kg_entity_type = KGEntityType(
                id_name=entity_type_id_name,
                description=entity_type_definition.description,
                attributes=entity_type_definition.attributes.model_dump(),
                grounding=entity_type_definition.grounding,
                grounded_source_name=grounded_source_name,
                active=entity_type_definition.active,
            )
            kg_entity_types.append(kg_entity_type)
            db_session.add(kg_entity_type)
        db_session.commit()

    # enable connector kg processing
    with get_session_with_current_tenant() as db_session:
        db_session.query(Connector).filter(Connector.id == cc_pair.connector_id).update(
            {"kg_processing_enabled": True}
        )
        db_session.commit()

    return ([doc1.id, doc2.id], cc_pair.id, kg_entity_types)


def wait_until_kg_processing_done(timeout: float = 60) -> bool:
    """
    Wait until KG processing is done. Returns True if the KG processing
    finished before the timeout, False otherwise.
    """
    start = time.monotonic()

    while time.monotonic() - start < timeout:
        time.sleep(1)
        if not is_kg_processing_blocked():
            return True
    return False


def test_kg_processing(
    kg_test_docs: tuple[list[str], int, KGEntityType],
) -> None:
    """Test KG processing."""
    # run extraction and clustering
    tenant_id = get_current_tenant_id()
    result = try_creating_kg_processing_task(tenant_id)
    assert result

    assert wait_until_kg_processing_done()

    # check entities
    with get_session_with_current_tenant() as db_session:
        entities_list = db_session.query(KGEntity).all()
        entities = {entity.name: entity for entity in entities_list}
    # should have the two TEST entities, the ACCOUNT and EMPLOYEE entities
    # should not have gmail.com as it is in the IGNORE_EMAIL_DOMAINS
    # the two docb entities should be clustered
    assert len(entities_list) == 4
    assert len(entities) == 4
    assert "test document doca" in entities
    assert "test document docb" in entities
    assert "outsider.com" in entities
    assert "dane" in entities
    # check properties of each entity
    doca_entity = entities["test document doca"]
    doca_id = doca_entity.id_name
    assert doca_entity.id_name.startswith("TEST::")
    assert doca_entity.entity_type_id_name == "TEST"
    assert doca_entity.document_id == "docA"
    assert doca_entity.entity_key == "Test Document docA"
    assert doca_entity.parent_key == "Test Document docB"
    assert doca_entity.attributes == {
        "team": "Team1",
        "stuff": ["a", "b", "c", "d", "e", "f", "g"],
    }
    docb_entity = entities["test document docb"]
    docb_id = docb_entity.id_name
    assert docb_entity.id_name.startswith("TEST::")
    assert docb_entity.entity_type_id_name == "TEST"
    assert docb_entity.document_id == "docB"
    assert docb_entity.entity_key == "Test Document docB"
    assert docb_entity.parent_key is None
    assert docb_entity.attributes == {
        "team": "Team2",
        "stuff": ["h", "i", "j", "k", "l", "m", "n"],
    }
    account_entity = entities["outsider.com"]
    account_id = account_entity.id_name
    assert account_entity.id_name.startswith("ACCOUNT::")
    assert account_entity.entity_type_id_name == "ACCOUNT"
    assert account_entity.document_id is None
    assert account_entity.entity_key is None
    assert account_entity.parent_key is None
    assert account_entity.attributes == {}
    employee_entity = entities["dane"]
    employee_id = employee_entity.id_name
    assert employee_entity.id_name.startswith("EMPLOYEE::")
    assert employee_entity.entity_type_id_name == "EMPLOYEE"
    assert employee_entity.document_id is None
    assert employee_entity.entity_key is None
    assert employee_entity.parent_key is None
    assert employee_entity.attributes == {}

    # check relationships
    with get_session_with_current_tenant() as db_session:
        relationships_list = db_session.query(KGRelationship).all()
        relationships = {
            relationship.relationship_type_id_name: relationship
            for relationship in relationships_list
        }
    assert len(relationships_list) == 4
    assert len(relationships) == 4
    assert "ACCOUNT__is_assignee_of__TEST" in relationships
    assert "EMPLOYEE__is_assignee_of__TEST" in relationships
    assert "TEST__is_parent_of__TEST" in relationships
    assert "TEST__has_subcomponent__TEST" in relationships
    # check properties of each relationship
    act_assignee_rel = relationships["ACCOUNT__is_assignee_of__TEST"]
    assert act_assignee_rel.source_node == account_id
    assert act_assignee_rel.target_node == docb_id
    assert act_assignee_rel.source_node_type == "ACCOUNT"
    assert act_assignee_rel.target_node_type == "TEST"
    assert act_assignee_rel.type == "is_assignee_of"
    emp_assignee_rel = relationships["EMPLOYEE__is_assignee_of__TEST"]
    assert emp_assignee_rel.source_node == employee_id
    assert emp_assignee_rel.target_node == doca_id
    assert emp_assignee_rel.source_node_type == "EMPLOYEE"
    assert emp_assignee_rel.target_node_type == "TEST"
    assert emp_assignee_rel.type == "is_assignee_of"
    parent_rel = relationships["TEST__is_parent_of__TEST"]
    assert parent_rel.source_node == docb_id
    assert parent_rel.target_node == doca_id
    assert parent_rel.source_node_type == "TEST"
    assert parent_rel.target_node_type == "TEST"
    assert parent_rel.type == "is_parent_of"
    subcomponent_rel = relationships["TEST__has_subcomponent__TEST"]
    assert subcomponent_rel.source_node == docb_id
    assert subcomponent_rel.target_node == doca_id
    assert subcomponent_rel.source_node_type == "TEST"
    assert subcomponent_rel.target_node_type == "TEST"
    assert subcomponent_rel.type == "has_subcomponent"

    # check staging tables are empty
    with get_session_with_current_tenant() as db_session:
        assert db_session.query(KGEntityExtractionStaging).count() == 0
        assert db_session.query(KGRelationshipExtractionStaging).count() == 0

    # check document kg_stage
    with get_session_with_current_tenant() as db_session:
        docs = db_session.query(Document).all()
        assert len(docs) == 2
        assert docs[0].kg_stage == KGStage.NORMALIZED
        assert docs[1].kg_stage == KGStage.NORMALIZED

    # check entity type attribute extraction
    with get_session_with_current_tenant() as db_session:
        entity_types_list = db_session.query(KGEntityType).all()
        entity_types = {
            entity_type.id_name: entity_type for entity_type in entity_types_list
        }
    assert len(entity_types_list) == 3
    assert len(entity_types) == 3
    assert "TEST" in entity_types
    assert "ACCOUNT" in entity_types
    assert "EMPLOYEE" in entity_types
    test_type_attr = entity_types["TEST"].parsed_attributes.attribute_values
    assert test_type_attr == {
        "team": KGAttributeTrackInfo(
            type=KGAttributeTrackType.VALUE,
            values={"Team1", "Team2"},
        ),
        "stuff": KGAttributeTrackInfo(
            type=KGAttributeTrackType.LIST,
            values=None,
        ),
    }
    account_type_attr = entity_types["ACCOUNT"].parsed_attributes.attribute_values
    assert account_type_attr == {}
    employee_type_attr = entity_types["EMPLOYEE"].parsed_attributes.attribute_values
    assert employee_type_attr == {}
