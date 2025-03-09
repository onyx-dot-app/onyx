import json
import os
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest
import responses

from onyx.connectors.backstage.connector import BackstageConnector, BACKSTAGE_ENTITY_KINDS
from onyx.connectors.models import Document
from onyx.connectors.exceptions import ConnectorValidationError, CredentialExpiredError

# Sample test data
MOCK_BASE_URL = "https://backstage.example.com"
MOCK_TOKEN_ENDPOINT = "https://auth.example.com/token"
MOCK_CLIENT_ID = "test-client-id"
MOCK_CLIENT_SECRET = "test-client-secret"
MOCK_ACCESS_TOKEN = "test-access-token"

# Sample entity data for mocking responses
MOCK_ENTITIES = {
    "items": [
        {
            "apiVersion": "backstage.io/v1alpha1",
            "kind": "Component",
            "metadata": {
                "name": "test-component",
                "namespace": "default",
                "description": "A test component",
                "annotations": {
                    "backstage.io/view-url": "https://backstage.example.com/catalog/default/component/test-component",
                }
            },
            "spec": {
                "type": "service",
                "lifecycle": "production",
                "owner": "team-a",
                "system": "test-system"
            }
        },
        {
            "apiVersion": "backstage.io/v1alpha1",
            "kind": "API",
            "metadata": {
                "name": "test-api",
                "namespace": "default",
                "description": "A test API",
            },
            "spec": {
                "type": "openapi",
                "lifecycle": "production",
                "owner": "team-b",
                "definition": "openapi: 3.0.0"
            }
        }
    ],
    "links": []
}

MOCK_TOKEN_RESPONSE = {
    "access_token": MOCK_ACCESS_TOKEN,
    "token_type": "Bearer",
    "expires_in": 3600
}


@pytest.fixture
def backstage_connector() -> BackstageConnector:
    """Create a Backstage connector instance."""
    connector = BackstageConnector(
        base_url=MOCK_BASE_URL,
        entity_kinds=[BACKSTAGE_ENTITY_KINDS.COMPONENT.value, BACKSTAGE_ENTITY_KINDS.API.value]
    )
    return connector


@pytest.fixture
def authenticated_connector(backstage_connector: BackstageConnector) -> BackstageConnector:
    """Create a Backstage connector with authentication."""
    with responses.RequestsMock() as rsps:
        # Mock token endpoint
        rsps.add(
            responses.POST,
            MOCK_TOKEN_ENDPOINT,
            json=MOCK_TOKEN_RESPONSE,
            status=200
        )
        
        # Load credentials
        backstage_connector.load_credentials({
            "backstage_client_id": MOCK_CLIENT_ID,
            "backstage_client_secret": MOCK_CLIENT_SECRET,
            "backstage_token_endpoint": MOCK_TOKEN_ENDPOINT
        })
    
    return backstage_connector


@responses.activate
def test_backstage_connector_authentication(backstage_connector: BackstageConnector) -> None:
    """Test authentication process."""
    # Mock the token endpoint
    responses.add(
        responses.POST,
        MOCK_TOKEN_ENDPOINT,
        json=MOCK_TOKEN_RESPONSE,
        status=200
    )
    
    # Load credentials
    credentials = {
        "backstage_client_id": MOCK_CLIENT_ID,
        "backstage_client_secret": MOCK_CLIENT_SECRET,
        "backstage_token_endpoint": MOCK_TOKEN_ENDPOINT
    }
    
    result = backstage_connector.load_credentials(credentials)
    
    # Check that credentials were loaded
    assert result == credentials
    assert backstage_connector.client_id == MOCK_CLIENT_ID
    assert backstage_connector.client_secret == MOCK_CLIENT_SECRET
    assert backstage_connector.token_endpoint == MOCK_TOKEN_ENDPOINT
    assert backstage_connector.access_token == MOCK_ACCESS_TOKEN


@responses.activate
def test_backstage_connector_authentication_failure(backstage_connector: BackstageConnector) -> None:
    """Test authentication failure handling."""
    # Mock the token endpoint with an error response
    responses.add(
        responses.POST,
        MOCK_TOKEN_ENDPOINT,
        json={"error": "invalid_client", "error_description": "Invalid client credentials"},
        status=401
    )
    
    # Attempt to load credentials
    credentials = {
        "backstage_client_id": "invalid-client",
        "backstage_client_secret": "invalid-secret",
        "backstage_token_endpoint": MOCK_TOKEN_ENDPOINT
    }
    
    # Should raise CredentialExpiredError
    with pytest.raises(CredentialExpiredError):
        backstage_connector.load_credentials(credentials)


@responses.activate
def test_backstage_connector_fetch_entities(authenticated_connector: BackstageConnector) -> None:
    """Test fetching entities."""
    # Mock the entities endpoint for components
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=component&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    # Mock the entities endpoint for APIs
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=api&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    # Get entities
    entities = []
    for entity_kind in [BACKSTAGE_ENTITY_KINDS.COMPONENT.value, BACKSTAGE_ENTITY_KINDS.API.value]:
        entities.extend(authenticated_connector._get_entities_by_kind(entity_kind))
    
    # Check that entities were fetched
    assert len(entities) == 4  # 2 entities per response, 2 responses
    assert entities[0]["kind"] == "Component"
    assert entities[0]["metadata"]["name"] == "test-component"


@responses.activate
def test_backstage_connector_process_entity(authenticated_connector: BackstageConnector) -> None:
    """Test processing an entity into a document."""
    entity = MOCK_ENTITIES["items"][0]
    
    document = authenticated_connector._process_entity(entity)
    
    # Check the resulting document
    assert isinstance(document, Document)
    assert document.semantic_identifier == "Component/test-component"
    assert document.source == "backstage"
    assert len(document.sections) == 1
    assert "A test component" in document.sections[0].text
    assert document.metadata["kind"] == "Component"
    assert document.metadata["name"] == "test-component"


@responses.activate
def test_backstage_connector_load_from_state(authenticated_connector: BackstageConnector) -> None:
    """Test loading documents from connector state."""
    # Mock the entities endpoints
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=component&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=api&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    # Get document batches
    all_docs = []
    document_batches = authenticated_connector.load_from_state()
    for batch in document_batches:
        all_docs.extend(batch)
    
    # Check that documents were created
    assert len(all_docs) == 4  # 2 entities per response, 2 responses
    assert all_docs[0].semantic_identifier == "Component/test-component"
    assert all_docs[1].semantic_identifier == "API/test-api"


@responses.activate
def test_backstage_connector_validate_settings(authenticated_connector: BackstageConnector) -> None:
    """Test validating connector settings."""
    # Mock the entities endpoint for validation
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?limit=1",
        json={"items": [MOCK_ENTITIES["items"][0]]},
        status=200
    )
    
    # Should not raise any exceptions
    authenticated_connector.validate_connector_settings()


@responses.activate
def test_backstage_connector_poll_source(authenticated_connector: BackstageConnector) -> None:
    """Test polling for updates."""
    # Mock the entities endpoints
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=component&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    responses.add(
        responses.GET,
        f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind=api&limit=50",
        json=MOCK_ENTITIES,
        status=200
    )
    
    # Call poll_source with dummy timestamps
    start_time = datetime(2023, 1, 1).timestamp()
    end_time = datetime(2023, 1, 2).timestamp()
    
    all_docs = []
    document_batches = authenticated_connector.poll_source(start_time, end_time)
    for batch in document_batches:
        all_docs.extend(batch)
    
    # Check that documents were created
    assert len(all_docs) == 4  # 2 entities per response, 2 responses


@pytest.mark.parametrize("entity_kinds", [
    ([BACKSTAGE_ENTITY_KINDS.ALL.value]),
    ([BACKSTAGE_ENTITY_KINDS.COMPONENT.value]),
    ([BACKSTAGE_ENTITY_KINDS.COMPONENT.value, BACKSTAGE_ENTITY_KINDS.API.value])
])
@responses.activate
def test_backstage_connector_entity_kinds(entity_kinds: list) -> None:
    """Test connector with different entity kinds configurations."""
    connector = BackstageConnector(
        base_url=MOCK_BASE_URL,
        entity_kinds=entity_kinds
    )
    
    # Mock the token endpoint
    responses.add(
        responses.POST,
        MOCK_TOKEN_ENDPOINT,
        json=MOCK_TOKEN_RESPONSE,
        status=200
    )
    
    # Load credentials
    connector.load_credentials({
        "backstage_client_id": MOCK_CLIENT_ID,
        "backstage_client_secret": MOCK_CLIENT_SECRET,
        "backstage_token_endpoint": MOCK_TOKEN_ENDPOINT
    })
    
    # Mock the entities endpoints
    if BACKSTAGE_ENTITY_KINDS.ALL.value in entity_kinds:
        responses.add(
            responses.GET,
            f"{MOCK_BASE_URL}/api/catalog/entities?limit=50",
            json=MOCK_ENTITIES,
            status=200
        )
    else:
        for kind in entity_kinds:
            responses.add(
                responses.GET,
                f"{MOCK_BASE_URL}/api/catalog/entities?filter=kind={kind}&limit=50",
                json=MOCK_ENTITIES,
                status=200
            )
    
    # Get document batches
    all_docs = []
    document_batches = connector.load_from_state()
    for batch in document_batches:
        all_docs.extend(batch)
    
    # Check that documents were created
    expected_count = 2 * (1 if BACKSTAGE_ENTITY_KINDS.ALL.value in entity_kinds else len(entity_kinds))
    assert len(all_docs) == expected_count
