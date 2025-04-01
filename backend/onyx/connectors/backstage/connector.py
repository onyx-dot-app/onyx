"""
Backstage Connector for Onyx.

This connector fetches data from a Spotify Backstage instance using its REST API.
It supports retrieving entities and their metadata from a Backstage catalog.

For more information about Backstage API, see:
https://backstage.spotify.com/docs/features/software-catalog/software-catalog-api
"""

from datetime import datetime, timedelta, timezone


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
        self.audience = credentials["backstage_saml_audience"]
        # Get initial access token
        self._refresh_access_token()        
        return credentials
    
    def _refresh_access_token(self):
        """
        Refresh the OAuth access token using client credentials flow.
        
        This method obtains a new access token from the OAuth server and updates the auth headers.
        """
        issuer = self.token_endpoint
        
        # Extract audience from base_url (domain name without protocol and path)
        audience = self.audience
        
        client_id = self.client_id
        secret = self.client_secret
        
        access_token = self._retrieve_token(client_id, secret, audience, issuer)
        self.access_token = access_token['access_token']
        self.headers["Authorization"] = f"Bearer {self.access_token}"
        
        # Set token expiry time if provided
        if 'expires_in' in access_token:
            self.token_expiry = datetime.now() + timedelta(seconds=access_token['expires_in'])
        else:
            # Default to 1 hour if not provided
            self.token_expiry = datetime.now() + timedelta(hours=1)
        
        logger.debug(f"Access token refreshed, valid until {self.token_expiry}")

   

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
        token_data = response.json()
        
        # Log token expiry information for debugging
        if 'expires_in' in token_data:
            logger.debug(f"Token expires in {token_data['expires_in']} seconds")
        else:
            logger.warning("No expires_in field in token response, using default 1 hour expiry")
        
        return token_data
        
   

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
        Fetch all entities of a specific kind from Backstage.
        
        This method handles pagination to retrieve ALL entities, not just the first batch.
        
        Args:
            kind: The kind of entity to fetch (component, api, etc.)
            
        Returns:
            List of entity dictionaries
        """
        self._ensure_valid_token()
        
        all_entities = []
        page_count = 0
        
        # Construct the proper URL with pagination parameters
        if kind == BACKSTAGE_ENTITY_KINDS.ALL.value:
            url = f"{self.api_url}/entities?limit={DEFAULT_PAGE_SIZE}"
        else:
            url = f"{self.api_url}/entities?filter=kind={kind.lower()}&limit={DEFAULT_PAGE_SIZE}"
        
        logger.info(f"Starting to fetch {kind} entities from {url}")
        
        # Follow pagination links until we've retrieved all entities
        while url:
            page_count += 1
            logger.info(f"Fetching {kind} entities - page {page_count}")
            
            # Add error handling with retry for network issues
            try:
                response = self._make_request_with_retry(url)
            except Exception as e:
                logger.error(f"Failed to fetch entities after retries: {e}")
                break
            
            # Handle both dictionary and list response formats
            data = response.json()
            
            # Get entities from the response
            if isinstance(data, dict):
                # Standard Backstage response format
                entities = data.get("items", [])
                
                # Look for next page link in various formats
                next_page = None
                
                # Format 1: Links array with rel=next
                for link in data.get("links", []):
                    if link.get("rel") == "next":
                        next_page = link.get("href")
                        break
                
                # Format 2: Pagination object with next property
                if not next_page and "pagination" in data:
                    next_page = data.get("pagination", {}).get("next")
                
                # Format 3: Next property at the root
                if not next_page:
                    next_page = data.get("next")
                    
            elif isinstance(data, list):
                # Direct list of entities (less common but possible)
                entities = data
                next_page = None
            else:
                logger.warning(f"Unexpected response type: {type(data)}")
                entities = []
                next_page = None
            
            # Make sure all entities have a kind property
            # Some Backstage instances might not normalize this properly
            for entity in entities:
                if "kind" not in entity and "metadata" in entity:
                    # Try to extract kind from the entity data
                    if entity.get("kind") is None:
                        # First check apiVersion for kind info (e.g., backstage.io/v1alpha1)
                        if "apiVersion" in entity:
                            parts = entity["apiVersion"].split("/")
                            if len(parts) > 1 and "kind" in parts[1]:
                                entity["kind"] = parts[1].capitalize()
                        # Then try to get it from metadata
                        elif "metadata" in entity and "annotations" in entity["metadata"]:
                            annotations = entity["metadata"]["annotations"]
                            for key in annotations:
                                if "backstage.io/entity-kind" in key:
                                    entity["kind"] = annotations[key].capitalize()
                                    break
            
            # Add entities to our collection
            all_entities.extend(entities)
            logger.info(f"Retrieved {len(entities)} {kind} entities on page {page_count} (total: {len(all_entities)})")
            
            # Ensure the next page URL is absolute
            if next_page and not next_page.startswith('http'):
                if next_page.startswith('/'):
                    base_url = '/'.join(self.api_url.split('/')[:3])  # Get scheme://host part
                    next_page = f"{base_url}{next_page}"
                else:
                    next_page = f"{self.api_url}/{next_page}"
                    
            # Move to next page or end loop
            url = next_page
        
        logger.info(f"Completed fetching {kind} entities - total: {len(all_entities)}")
        return all_entities

    def _make_request_with_retry(self, url: str, max_retries: int = 3) -> requests.Response:
        """
        Make an HTTP request with automatic retries for certain failure conditions.
        """
        retry_count = 0
        
        # Always ensure valid token before making any request
        self._ensure_valid_token()  # Add this line
        
        while retry_count < max_retries:
            try:
                response = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                
                # Handle rate limiting with exponential backoff
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5))
                    sleep_time = min(retry_after, 60) * (2 ** retry_count)
                    logger.warning(f"Rate limited. Retrying after {sleep_time} seconds")
                    time.sleep(sleep_time)
                    retry_count += 1
                    continue
                
                # Raise for other errors
                response.raise_for_status()
                return response
                
            except requests.exceptions.ConnectionError as e:
                # Network errors - retry with backoff
                retry_count += 1
                sleep_time = 2 ** retry_count
                logger.warning(f"Connection error: {e}. Retrying in {sleep_time} seconds")
                time.sleep(sleep_time)
                
            except requests.exceptions.Timeout as e:
                # Timeout errors - retry with backoff
                retry_count += 1
                sleep_time = 2 ** retry_count
                logger.warning(f"Request timeout: {e}. Retrying in {sleep_time} seconds")
                time.sleep(sleep_time)
                
            except requests.exceptions.RequestException as e:
                # Other request errors - don't retry
                logger.error(f"Request failed: {e}")
                raise
        
        # If we get here, we've exceeded our retry limit
        raise Exception(f"Failed to fetch data from {url} after {max_retries} attempts")

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
        """
        Process a Backstage entity into a human-readable document.
        
        Args:
            entity: The entity data from Backstage
            
        Returns:
            Document object with human-readable sections
        """
        entity_id = generate_entity_id(entity)
        entity_link = get_entity_link(self.base_url, entity)
        
        # Extract metadata for easier access
        metadata = extract_entity_metadata(entity)
        kind = metadata.get('kind', 'Unknown')
        name = metadata.get('name', 'Unnamed Entity')
        namespace = metadata.get('namespace', 'default')
        description = metadata.get('description', 'No description provided')
        
        # Create multiple sections for better organization and readability
        sections = []
        
        # Overview section with a conversational introduction to the entity
        overview_text = f"# {name}\n\n"
        overview_text += f"This is a **{kind.title()}** in the **{namespace}** namespace.\n\n"
        
        if description:
            overview_text += f"{description}\n\n"
        else:
            overview_text += f"No description is available for this {kind.lower()}.\n\n"
            
        # Add lifecycle info if available
        if entity.get("spec", {}).get("lifecycle"):
            lifecycle = entity["spec"]["lifecycle"]
            overview_text += f"This {kind.lower()} is in the **{lifecycle}** lifecycle stage.\n"
        
        # Add owner info in a conversational way
        if entity.get("spec", {}).get("owner"):
            owner = entity["spec"]["owner"]
            overview_text += f"This {kind.lower()} is owned by **{owner}**.\n"
        
        # Add system info for components
        if kind.lower() == "component" and entity.get("spec", {}).get("system"):
            system = entity["spec"]["system"]
            overview_text += f"This component is part of the **{system}** system.\n"
        
        # Add type info
        if entity.get("spec", {}).get("type"):
            entity_type = entity["spec"]["type"]
            overview_text += f"This {kind.lower()} is of type **{entity_type}**.\n"
            
        sections.append(Section(link=entity_link, text=overview_text))
        
        # Technical details section with additional information
        if kind.lower() == "api":
            tech_section = self._format_api_details(entity)
            if tech_section:
                sections.append(Section(link=entity_link, text=tech_section))
        elif kind.lower() == "component":
            tech_section = self._format_component_details(entity)
            if tech_section:
                sections.append(Section(link=entity_link, text=tech_section))
        
        # Relations section in a more conversational format
        if "relations" in entity:
            relations_text = self._format_relations_human_readable(
                entity.get("relations", []), name, kind
            )
            if relations_text:
                sections.append(Section(link=entity_link, text=relations_text))
        
        # Annotations section - convert annotations to human-readable format
        annotations_text = self._format_annotations_human_readable(
            entity.get("metadata", {}).get("annotations", {})
        )
        if annotations_text:
            sections.append(Section(link=entity_link, text=annotations_text))
        
        # Create document with enriched metadata
        document = Document(
            id=entity_id,
            sections=sections,
            source=DocumentSource.BACKSTAGE,
            semantic_identifier=f"{metadata['kind']}/{metadata['name']}",
            metadata=self._enrich_metadata(metadata, entity),
            doc_updated_at=datetime.now().replace(
                tzinfo=timezone.utc
            ),
        )
        
        return document
    
    def _format_api_details(self, entity: Dict[str, Any]) -> str:
        """Format API-specific details in a human-readable way"""
        spec = entity.get("spec", {})
        text = "## API Details\n\n"
        
        # Definition type
        if spec.get("type"):
            text += f"This API is documented using **{spec.get('type')}**.\n"
            
        # API definition or specification
        if spec.get("definition"):
            text += "\nHere is a summary of the API definition:\n"
            definition = spec.get("definition")
            if len(definition) > 500:
                # Truncate long definitions
                text += f"```\n{definition[:500]}...\n```\n"
            else:
                text += f"```\n{definition}\n```\n"
                
        return text
    
    def _format_component_details(self, entity: Dict[str, Any]) -> str:
        """Format Component-specific details in a human-readable way"""
        spec = entity.get("spec", {})
        text = "## Component Details\n\n"
        
        component_type = spec.get("type", "Unknown")
        text += f"This component is a **{component_type}**.\n"
        
        # Add subcomponentOf if present
        if spec.get("subcomponentOf"):
            text += f"This is a subcomponent of **{spec.get('subcomponentOf')}**.\n"
            
        # Add providesApis if present
        if spec.get("providesApis"):
            apis = spec.get("providesApis", [])
            if apis:
                text += "\nThis component provides the following APIs:\n"
                for api in apis:
                    text += f"- {api}\n"
                    
        # Add consumesApis if present
        if spec.get("consumesApis"):
            apis = spec.get("consumesApis", [])
            if apis:
                text += "\nThis component consumes the following APIs:\n"
                for api in apis:
                    text += f"- {api}\n"
                    
        # Add dependsOn if present
        if spec.get("dependsOn"):
            deps = spec.get("dependsOn", [])
            if deps:
                text += "\nThis component depends on:\n"
                for dep in deps:
                    text += f"- {dep}\n"
                    
        return text
    
    def _format_relations_human_readable(
        self, relations: List[Dict[str, Any]], entity_name: str, entity_kind: str
    ) -> str:
        """
        Format entity relations in a human-readable, conversational way.
        
        Args:
            relations: List of relation objects
            entity_name: Name of the current entity
            entity_kind: Kind of the current entity
            
        Returns:
            Human-readable text describing the relationships
        """
        if not relations:
            return ""
            
        # Group relations by type
        relation_by_type = {}
        for relation in relations:
            rel_type = relation.get("type", "unknown")
            target = relation.get("target", {})
            target_kind = target.get("kind", "entity")
            target_name = target.get("name", "unknown")
            target_namespace = target.get("namespace", "default")
            
            if rel_type not in relation_by_type:
                relation_by_type[rel_type] = []
                
            relation_by_type[rel_type].append({
                "kind": target_kind,
                "name": target_name,
                "namespace": target_namespace
            })
            
        # Format as conversational text
        text = "## Relationships\n\n"
        text += f"The {entity_kind.lower()} **{entity_name}** has the following relationships:\n\n"
        
        for rel_type, targets in relation_by_type.items():
            # Make relation type more human readable
            readable_rel = rel_type.replace('-', ' ').replace('_', ' ').title()
            
            if rel_type == "ownedBy":
                text += f"This {entity_kind.lower()} is owned by "
            elif rel_type == "partOf":
                text += f"This {entity_kind.lower()} is part of "
            elif rel_type == "consumesApi":
                text += f"This {entity_kind.lower()} consumes these APIs: "
            elif rel_type == "providesApi":
                text += f"This {entity_kind.lower()} provides these APIs: "
            elif rel_type == "dependsOn":
                text += f"This {entity_kind.lower()} depends on "
            else:
                text += f"{readable_rel}: "
                
            # Add targets
            if len(targets) == 1:
                target = targets[0]
                text += f"the {target['kind'].lower()} **{target['name']}**"
                if target['namespace'] != 'default':
                    text += f" in the {target['namespace']} namespace"
                text += ".\n\n"
            else:
                text += "\n"
                for target in targets:
                    text += f"- The {target['kind'].lower()} **{target['name']}**"
                    if target['namespace'] != 'default':
                        text += f" in the {target['namespace']} namespace"
                    text += "\n"
                text += "\n"
                
        return text
    
    def _format_annotations_human_readable(self, annotations: Dict[str, Any]) -> str:
        """
        Format entity annotations in a human-readable way.
        
        Args:
            annotations: Dictionary of annotations
            
        Returns:
            Human-readable text describing the annotations
        """
        if not annotations:
            return ""
            
        important_annotations = {
            "backstage.io/techdocs-ref": "Technical documentation",
            "github.com/project-slug": "GitHub repository",
            "backstage.io/source-location": "Source code location",
            "backstage.io/kubernetes-id": "Kubernetes ID",
            "backstage.io/kubernetes-namespace": "Kubernetes namespace",
            "backstage.io/view-url": "View in Backstage",
            "jenkins.io/job-full-name": "Jenkins job",
            "jira/project-key": "Jira project",
            "sentry.io/project-slug": "Sentry project",
            "grafana/dashboard-selector": "Grafana dashboard",
            "sonarqube.org/project-key": "SonarQube project"
        }
        
        # Filter for important annotations only
        relevant_annotations = {}
        for key, value in annotations.items():
            for important_key, label in important_annotations.items():
                if key.endswith(important_key) or key == important_key:
                    relevant_annotations[label] = value
                    break
                    
        if not relevant_annotations:
            # If no relevant annotations found, pick some general ones
            for key, value in annotations.items():
                if len(relevant_annotations) >= 5:  # Limit to 5 annotations
                    break
                # Skip very technical annotations
                if "backstage.io/managed-by-location" in key or "backstage.io/managed-by-origin-location" in key:
                    continue
                # Make key more readable
                readable_key = key.split('/')[-1].replace('-', ' ').replace('_', ' ').title()
                relevant_annotations[readable_key] = value
                
        if not relevant_annotations:
            return ""
            
        text = "## Additional Information\n\n"
        
        for label, value in relevant_annotations.items():
            # Handle different value types
            if isinstance(value, (dict, list)):
                import json
                try:
                    value_str = f"has a complex value (details available in Backstage)"
                except:
                    value_str = "has a complex value"
            elif "http" in value and "://" in value:
                value_str = f"is available at [{value}]({value})"
            else:
                value_str = f"is {value}"
                
            text += f"The {label} {value_str}.\n"
            
        return text
    
    def _enrich_metadata(self, metadata: Dict[str, Any], entity: Dict[str, Any]) -> Dict[str, Any]:
        """Add additional searchable metadata fields"""
        # Start with a clean dictionary to ensure all values are strings
        enriched = {}
        
        # Convert basic metadata to strings
        for key, value in metadata.items():
            if key != "annotations":  # Handle annotations separately
                enriched[key] = str(value) if value is not None else ""
        
        # Add additional fields, converting to strings
        if "spec" in entity:
            if "owner" in entity["spec"]:
                enriched["owner"] = str(entity["spec"]["owner"])
            if "lifecycle" in entity["spec"]:
                enriched["lifecycle"] = str(entity["spec"]["lifecycle"])
            if "type" in entity["spec"]:
                enriched["entity_type"] = str(entity["spec"]["type"])
            if "system" in entity["spec"]:
                enriched["system"] = str(entity["spec"]["system"])
                
        # Add relation information in a structured way
        if "relations" in entity:
            # Create dedicated fields for important relation types
            for relation in entity.get("relations", []):
                rel_type = relation.get("type")
                target = relation.get("target", {})
                target_name = target.get("name", "")
                
                if rel_type == "ownedBy":
                    enriched["owned_by"] = target_name
                elif rel_type == "partOf":
                    enriched["part_of"] = target_name
                elif rel_type == "providesApi":
                    if "provides_apis" not in enriched:
                        enriched["provides_apis"] = target_name
                    else:
                        enriched["provides_apis"] += f", {target_name}"
                elif rel_type == "consumesApi":
                    if "consumes_apis" not in enriched:
                        enriched["consumes_apis"] = target_name
                    else:
                        enriched["consumes_apis"] += f", {target_name}"
        
        # Add key annotations as separate fields for better searchability
        if "metadata" in entity and "annotations" in entity["metadata"]:
            # Extract important annotations as dedicated fields
            annotations = entity["metadata"]["annotations"]
            if "github.com/project-slug" in annotations:
                enriched["github_repo"] = annotations["github.com/project-slug"]
                
            if "backstage.io/techdocs-ref" in annotations:
                enriched["techdocs_ref"] = annotations["backstage.io/techdocs-ref"]
                
            # Store all annotations in a single string field
            annotation_text = ""
            for key, value in annotations.items():
                if isinstance(value, (dict, list)):
                    import json
                    try:
                        annotation_text += f"{key}: {json.dumps(value)}\n"
                    except:
                        annotation_text += f"{key}: [Complex value]\n"
                else:
                    annotation_text += f"{key}: {value}\n"
            enriched["annotations"] = annotation_text
        
        return enriched

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Load entities from Backstage and convert them to documents.
        
        Yields:
            Batches of Document objects
        """
        doc_batch: List[Document] = []
        processed_ids = set()  # Track IDs to avoid duplicates
        
        # Process entity kinds one at a time to avoid memory issues with large catalogs
        for kind in self.entity_kinds:
            try:
                if kind == BACKSTAGE_ENTITY_KINDS.ALL.value:
                    # If "all" is specified, process each known entity kind separately
                    # This ensures we get complete coverage and avoids pagination issues
                    for specific_kind in [
                        k.value for k in BACKSTAGE_ENTITY_KINDS if k != BACKSTAGE_ENTITY_KINDS.ALL
                    ]:
                        entities = self._get_entities_by_kind(specific_kind)
                        logger.info(f"Found {len(entities)} entities of kind: {specific_kind}")
                        doc_batch = self._process_entities_into_batch(entities, doc_batch, processed_ids)
                        # Yield complete batches
                        while len(doc_batch) >= self.batch_size:
                            yield doc_batch[:self.batch_size]
                            doc_batch = doc_batch[self.batch_size:]
                else:
                    # Process the specific kind
                    entities = self._get_entities_by_kind(kind)
                    logger.info(f"Found {len(entities)} entities of kind: {kind}")
                    doc_batch = self._process_entities_into_batch(entities, doc_batch, processed_ids)
                    # Yield complete batches
                    while len(doc_batch) >= self.batch_size:
                        yield doc_batch[:self.batch_size]
                        doc_batch = doc_batch[self.batch_size:]
                        
            except Exception as e:
                logger.exception(f"Error fetching entities of kind {kind}: {e}")
        
        # Yield any remaining documents
        if doc_batch:
            yield doc_batch

    def _process_entities_into_batch(
        self, entities: List[Dict[str, Any]], 
        current_batch: List[Document], 
        processed_ids: set
    ) -> List[Document]:
        """
        Process entities into document batches, avoiding duplicates.
        
        Args:
            entities: List of entity dictionaries
            current_batch: Current batch of documents being built
            processed_ids: Set of already processed entity IDs
            
        Returns:
            Updated batch of documents
        """
        for entity in entities:
            try:
                # Generate ID first to check for duplicates
                entity_id = generate_entity_id(entity)
                
                # Skip if we've already processed this entity
                if entity_id in processed_ids:
                    continue
                    
                document = self._process_entity(entity)
                current_batch.append(document)
                processed_ids.add(entity_id)
                
            except Exception as e:
                entity_name = entity.get("metadata", {}).get("name", "unknown")
                logger.exception(f"Error processing entity {entity_name}: {e}")
                
        return current_batch

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
        connector = BackstageConnector("https://demo.backstage.io/")
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