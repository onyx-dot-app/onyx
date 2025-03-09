"""
Backstage Connector for Onyx.

This connector fetches data from a Spotify Backstage instance using its REST API.
It supports retrieving entities and their metadata from a Backstage catalog.

For more information about Backstage API, see:
https://backstage.spotify.com/docs/features/software-catalog/software-catalog-api
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

import requests
from requests.exceptions import RequestException

from onyx.configs.constants import DocumentSource
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.exceptions import ConnectorValidationError, CredentialExpiredError, InsufficientPermissionsError
from onyx.connectors.interfaces import GenerateDocumentsOutput, LoadConnector, PollConnector
from onyx.connectors.models import Document, Section
from onyx.connectors.models import ConnectorMissingCredentialError

from onyx.utils.logger import setup_logger

SecondsSinceUnixEpoch = float

from .constants import (
    DEFAULT_API_PATH,
    ENTITIES_PATH,
    ENTITY_BY_NAME_PATH,
    DEFAULT_PAGE_SIZE,
    REQUEST_TIMEOUT,
)
from .utils import (
    format_entity_text,
    extract_entity_metadata,
    generate_entity_id,
    get_entity_link,
)

logger = setup_logger()


class BACKSTAGE_ENTITY_KINDS(str, Enum):
    """Entity kinds supported by Backstage catalog"""
    COMPONENT = "component"
    API = "api"
    RESOURCE = "resource"
    SYSTEM = "system"
    DOMAIN = "domain"
    GROUP = "group"
    USER = "user"
    TEMPLATE = "template"
    LOCATION = "location"
    # Allow fetching all entities
    ALL = "all"


class BackstageConnector(PollConnector, LoadConnector):
    """
    Connector for Spotify Backstage.
    
    This connector fetches data from a Backstage instance by querying its
    catalog API for entities and their metadata.
    """

    def __init__(
        self,
        base_url: str,
        entity_kinds: List[str] = [BACKSTAGE_ENTITY_KINDS.ALL.value],
        batch_size: int = INDEX_BATCH_SIZE,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Backstage connector.
        
        Args:
            base_url: The base URL of the Backstage instance (e.g., https://backstage.example.com)
            entity_kinds: List of entity kinds to fetch (default: ["all"] to fetch all entities)
            batch_size: Number of documents to yield at once
        """
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{DEFAULT_API_PATH}"
        self.entity_kinds = entity_kinds
        self.batch_size = batch_size
        self.client_id = None
        self.client_secret = None
        self.token_endpoint = None
        self.access_token = None
        self.token_expiry = None
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        Load OAuth credentials for Backstage.
        
        Args:
            credentials: Dictionary containing OAuth credentials
                Expected format: {
                    "backstage_client_id": "your-client-id",
                    "backstage_client_secret": "your-client-secret",
                    "backstage_token_endpoint": "your-token-endpoint"
                }
                
        Returns:
            The credentials if valid, or None if no credentials are needed
            
        Raises:
            ConnectorMissingCredentialError: If required credentials are missing
        """
        if not credentials:
            return None
            
        if "backstage_client_id" not in credentials or "backstage_client_secret" not in credentials:
            raise ConnectorMissingCredentialError(
                "Both backstage_client_id and backstage_client_secret are required for Backstage OAuth authentication"
            )
        
        if "backstage_token_endpoint" not in credentials:
            raise ConnectorMissingCredentialError(
                "backstage_token_endpoint is required for Backstage OAuth authentication"
            )
            
        self.client_id = credentials["backstage_client_id"]
        self.client_secret = credentials["backstage_client_secret"]
        self.token_endpoint = credentials["backstage_token_endpoint"]
        
        # Get initial access token
        self._refresh_access_token()        
        return credentials
    
    def _refresh_access_token(self):
        issuer = self.token_endpoint
        audience = 'portal.services.as24.tech' # Make this configurable
        client_id = self.client_id
        secret = self.client_secret
        access_token = self._retrieve_token(client_id, secret, audience, issuer)
        self.access_token = access_token['access_token']
        self.headers["Authorization"] = f"Bearer {self.access_token}"
        

    def _retrieve_token(self, client_id, secret, audience, issuer):
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'cache-control': 'no-cache'
        }
        data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': secret,
            'audience': audience
        }

        response = requests.post(issuer, headers=headers, data=data)
        response.raise_for_status()
        return response.json()
        
   

    def _ensure_valid_token(self) -> None:
        """
        Ensure the OAuth token is valid, refreshing if necessary.
        """
        # If token is missing or expired (or about to expire in the next minute), refresh it
        if (not self.access_token or 
            not self.token_expiry or 
            datetime.now() + timedelta(minutes=1) >= self.token_expiry):
            self._refresh_access_token()

    def _get_entities_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        """
        Fetch entities of a specific kind from Backstage.
        
        Args:
            kind: The entity kind to fetch
            
        Returns:
            List of entity objects
            
        Raises:
            ConnectorValidationError: If the API returns a validation error
            CredentialExpiredError: If authentication fails
            Exception: For other API errors
        """
        try:
            # Ensure we have a valid token before making the request
            self._ensure_valid_token()
            
            if kind == BACKSTAGE_ENTITY_KINDS.ALL.value:
                # Fetch all entities
                url = f"{self.api_url}{ENTITIES_PATH}"
            else:
                # Fetch entities of specific kind
                url = f"{self.api_url}{ENTITIES_PATH}?filter=kind={kind}"
            
            # Add pagination parameters
            if "?" in url:
                url += f"&limit={DEFAULT_PAGE_SIZE}"
            else:
                url += f"?limit={DEFAULT_PAGE_SIZE}"
                
            all_entities = []
            while url:
                logger.debug(f"Fetching Backstage entities from: {url}")
                response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                
                # If token expired, refresh and retry once
                if response.status_code == 401:
                    self._refresh_access_token()
                    response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                
                response.raise_for_status()
                
                data = response.json()
                # Handle the response based on its type
                if isinstance(data, dict):
                    entities = data.get("items", [])
                    
                    # Check for pagination in dictionary format
                    next_page = None
                    for link in data.get("links", []):
                        if link.get("rel") == "next":
                            next_page = link.get("href")
                            break
                elif isinstance(data, list):
                    # API directly returned a list of entities
                    all_entities = data
                    next_page = None  # No pagination info in list format
                else:
                    logger.warning(f"Unexpected response type: {type(data)}")
                    entities = []
                    next_page = None
                
                url = next_page
            
            return all_entities
                
        except RequestException as e:
            if e.response is not None:
                if e.response.status_code == 401:
                    raise CredentialExpiredError(f"Authentication failed: {e}")
                elif e.response.status_code == 403:
                    raise InsufficientPermissionsError(f"Insufficient permissions: {e}")
                elif e.response.status_code == 400:
                    raise ConnectorValidationError(f"Invalid request: {e}")
            raise Exception(f"Error fetching Backstage entities: {e}")

    def _get_entity_details(self, kind: str, namespace: str, name: str) -> Dict[str, Any]:
        """
        Fetch detailed information about a specific entity.
        
        Args:
            kind: Entity kind
            namespace: Entity namespace
            name: Entity name
            
        Returns:
            Detailed entity information
        """
        # Ensure we have a valid token
        self._ensure_valid_token()
        
        url = f"{self.api_url}{ENTITY_BY_NAME_PATH}/{namespace}/{kind}/{name}"
        response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
        
        # If token expired, refresh and retry once
        if response.status_code == 401:
            self._refresh_access_token()
            response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            
        response.raise_for_status()
        return response.json()

    def _process_entity(self, entity: Dict[str, Any]) -> Document:
        entity_id = generate_entity_id(entity)
        entity_link = get_entity_link(self.base_url, entity)
        
        # Create multiple sections for better organization
        sections = []
        
        # Overview section with most important entity details
        metadata = extract_entity_metadata(entity)
        overview_text = (
            f"# {metadata.get('name', 'Unnamed Entity')}\n\n"
            f"**Kind**: {metadata.get('kind', 'Unknown')}\n"
            f"**Description**: {metadata.get('description', 'No description provided')}\n\n"
        )
        sections.append(Section(link=entity_link, text=overview_text))
        
        # Technical details section with more verbose content
        tech_details = format_entity_text(entity)
        if tech_details:
            sections.append(Section(link=entity_link, text=tech_details))
        
        # Relations section if available
        if "relations" in entity:
            relations_text = self._format_relations(entity.get("relations", []))
            if relations_text:
                sections.append(Section(link=entity_link, text=relations_text))
        
        # Create document with enriched metadata
        document = Document(
            id=entity_id,
            sections=sections,
            source=DocumentSource.BACKSTAGE,
            semantic_identifier=f"{metadata['kind']}/{metadata['name']}",
            metadata=self._enrich_metadata(metadata, entity),
            doc_updated_at=datetime.now(),
        )
        
        return document
    
    def _format_relations(self, relations: List[Dict[str, Any]]) -> str:
        """Format entity relations into searchable text"""
        if not relations:
            return ""
            
        text = "## Relations\n\n"
        for relation in relations:
            target = relation.get("target", {})
            text += (f"- **{relation.get('type', 'Related to')}**: "
                    f"{target.get('kind', '')} {target.get('name', 'Unknown')}\n")
        return text
    
    def _enrich_metadata(self, metadata: Dict[str, Any], entity: Dict[str, Any]) -> Dict[str, Any]:
        """Add additional searchable metadata fields"""
        enriched = metadata.copy()
        
        # Add owner information if available
        if "spec" in entity and "owner" in entity["spec"]:
            enriched["owner"] = entity["spec"]["owner"]
        
        # Add lifecycle information
        if "spec" in entity and "lifecycle" in entity["spec"]:
            enriched["lifecycle"] = entity["spec"]["lifecycle"]
        
        # Extract tags for filtering
        if "metadata" in entity and "tags" in entity["metadata"]:
            enriched["tags"] = entity["metadata"]["tags"]
            
        # Extract links for reference
        if "metadata" in entity and "links" in entity["metadata"]:
            enriched["links"] = [link.get("url") for link in entity["metadata"]["links"] 
                                if "url" in link]
        
        return enriched

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Load entities from Backstage and convert them to documents.
        
        Yields:
            Batches of Document objects
        """
        doc_batch: List[Document] = []
        
        for kind in self.entity_kinds:
            try:
                logger.info(f"Fetching Backstage entities of kind: {kind}")
                entities = self._get_entities_by_kind(kind)
                
                logger.info(f"Found {len(entities)} entities of kind: {kind}")
                
                for entity in entities:
                    try:
                        document = self._process_entity(entity)
                        doc_batch.append(document)
                        
                        if len(doc_batch) >= self.batch_size:
                            yield doc_batch
                            doc_batch = []
                    except Exception as e:
                        entity_name = entity.get("metadata", {}).get("name", "unknown")
                        logger.exception(f"Error processing entity {entity_name}: {e}")
            except Exception as e:
                logger.exception(f"Error fetching entities of kind {kind}: {e}")
        
        # Yield any remaining documents
        if doc_batch:
            yield doc_batch

    def validate_connector_settings(self) -> None:
        """
        Validate connector settings and connectivity to Backstage.
        
        Raises:
            ConnectorValidationError: If settings are invalid or connection fails
            ConnectorMissingCredentialError: If OAuth credentials are missing
        """
        if not self.base_url:
            raise ConnectorValidationError("Backstage base URL is required")
            
        if not self.client_id or not self.client_secret or not self.token_endpoint:
            raise ConnectorMissingCredentialError(
                "backstage_client_id, backstage_client_secret, and backstage_token_endpoint are required for authentication"
            )
        
        try:
            # Ensure we have a valid token
            self._ensure_valid_token()
            
            # Test connection by fetching 1 component
            url = f"{self.api_url}{ENTITIES_PATH}?limit=1"
            response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            # If we get here, the connection is successful
            logger.info(f"Successfully connected to Backstage at {self.base_url}")
        except RequestException as e:
            if e.response is not None:
                if e.response.status_code == 401:
                    raise CredentialExpiredError(f"Authentication failed: {e}")
                elif e.response.status_code == 403:
                    raise InsufficientPermissionsError(f"Insufficient permissions: {e}")
            raise ConnectorValidationError(f"Failed to connect to Backstage at {self.base_url}: {e}")

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """
        Poll the Backstage API for changes within the specified time window.
        
        Args:
            start: Start time in seconds since Unix epoch
            end: End time in seconds since Unix epoch
            
        Returns:
            Generator yielding document batches
            
        Raises:
            ConnectorMissingCredentialError: If OAuth credentials are missing
        """
        if not self.client_id or not self.client_secret or not self.token_endpoint:
            raise ConnectorMissingCredentialError(
                "backstage_client_id, backstage_client_secret, and backstage_token_endpoint are required"
            )

        # Currently, Backstage doesn't support filtering by update time
        # So we fetch all entities and let Onyx handle deduplication
        yield from self.load_from_state()


if __name__ == "__main__":
    import os
    
    # Set up logging for debugging
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Example of how to use the connector with proper error handling
    try:
        connector = BackstageConnector("https://portal.services.as24.tech/")
        connector.load_credentials({
                "backstage_client_id": os.environ["BACKSTAGE_CLIENT_ID"],
                "backstage_client_secret": os.environ["BACKSTAGE_CLIENT_SECRET"],
                "backstage_token_endpoint": os.environ["BACKSTAGE_TOKEN_ENDPOINT"],
            }
        )
        
        document_batches = connector.load_from_state()
        batch = next(document_batches, None)
        if batch:
            print(f"Successfully retrieved {len(batch)} documents")
        else:
            print("No documents found")
    except Exception as e:
        print(f"Error: {str(e)}")