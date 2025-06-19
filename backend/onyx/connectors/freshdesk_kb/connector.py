"""Freshdesk Knowledge Base connector implementation for Onyx."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import requests
from bs4 import BeautifulSoup

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FRESHDESK_KB_ID_PREFIX = "FRESHDESK_KB_"

# Fields to extract from solution articles
_SOLUTION_ARTICLE_FIELDS_TO_INCLUDE = {
    "id",
    "title",
    "description",  # HTML content
    "description_text",  # Plain text content
    "folder_id",
    "category_id",
    "status",  # 1: Draft, 2: Published
    "tags",
    "thumbs_up",
    "thumbs_down",
    "hits",
    "created_at",
    "updated_at",
}


def _clean_html_content(html_content: str) -> str:
    """Cleans HTML content, extracting plain text.
    
    Uses BeautifulSoup to parse HTML and get text.
    """
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        text_parts = [
            p.get_text(separator=" ", strip=True)
            for p in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"])
        ]
        if not text_parts:
            return soup.get_text(separator=" ", strip=True)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Error cleaning HTML with BeautifulSoup: {e}")
        return html_content


def _create_metadata_from_article(
    article: dict, domain: str, portal_url: Optional[str], portal_id: Optional[str]
) -> dict:
    """Creates a metadata dictionary from a Freshdesk solution article."""
    metadata: dict[str, Any] = {}
    article_id = article.get("id")

    for key, value in article.items():
        if key not in _SOLUTION_ARTICLE_FIELDS_TO_INCLUDE:
            continue
        # Skip None or empty lists
        if value is None or (isinstance(value, list) and not value):
            continue
        metadata[key] = value
    
    # Construct URLs
    if article_id:
        # Agent URL (the one with portalId)
        if portal_url and portal_id:
            portal_base = portal_url.rstrip("/")
            metadata["agent_url"] = f"{portal_base}/a/solutions/articles/{article_id}?portalId={portal_id}"
        else:
            logger.warning(f"Could not construct agent_url for article {article_id}: missing portal_url or portal_id.")

        # Public/API Domain URL
        if domain:
            public_portal_base = f"https://{domain.rstrip('/')}"
            metadata["public_url"] = f"{public_portal_base}/a/solutions/articles/{article_id}"
        else:
            logger.warning(f"Could not construct public_url for article {article_id}: missing domain.")
            
    # Convert status number to human-readable string
    status_number = article.get("status")
    if status_number == 1:
        metadata["status_string"] = "Draft"
    elif status_number == 2:
        metadata["status_string"] = "Published"
    else:
        metadata["status_string"] = "Unknown"

    return metadata


def _create_doc_from_article(
    article: dict, domain: str, portal_url: Optional[str], portal_id: Optional[str]
) -> Document:
    """Creates an Onyx Document from a Freshdesk solution article."""
    article_id = str(article.get("id", ""))
    if not article_id:
        raise ValueError("Article missing required 'id' field")
        
    title = article.get("title", "Untitled Article")
    
    # Get text content - prefer description_text over description
    text_content = article.get("description_text", "")
    if not text_content and article.get("description"):
        # Fall back to cleaning HTML if no plain text available
        text_content = _clean_html_content(article.get("description", ""))
    
    if not text_content:
        text_content = "No content available"
    
    # Parse updated_at timestamp
    updated_at_str = article.get("updated_at")
    if updated_at_str:
        try:
            doc_updated_at = datetime.fromisoformat(
                updated_at_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            logger.warning(
                f"Failed to parse updated_at timestamp for article {article_id}: "
                f"{updated_at_str}"
            )
            doc_updated_at = datetime.now(timezone.utc)
    else:
        doc_updated_at = datetime.now(timezone.utc)
    
    # Create metadata
    metadata = _create_metadata_from_article(article, domain, portal_url, portal_id)
    
    # Determine the best link to use
    link = (
        metadata.get("agent_url")
        or metadata.get("public_url")
        or f"https://{domain}/a/solutions/articles/{article_id}"
    )
    
    document = Document(
        id=_FRESHDESK_KB_ID_PREFIX + article_id,
        sections=[
            TextSection(
                link=link,
                text=text_content,
            )
        ],
        source=DocumentSource.FRESHDESK_KB,
        semantic_identifier=title,
        metadata=metadata,
        doc_updated_at=doc_updated_at,
    )
    
    return document


class FreshdeskKnowledgeBaseConnector(LoadConnector, PollConnector, SlimConnector):
    """Onyx Connector for fetching Freshdesk Knowledge Base (Solution Articles).
    
    Implements LoadConnector for full indexing and PollConnector for incremental updates.
    """
    def __init__(
        self,
        freshdesk_folder_id: Optional[str] = None,
        freshdesk_domain: Optional[str] = None,
        freshdesk_api_key: Optional[str] = None,
        freshdesk_portal_url: Optional[str] = None,
        freshdesk_portal_id: Optional[str] = None,
        batch_size: int = INDEX_BATCH_SIZE,
        connector_specific_config: Optional[dict] = None,
        freshdesk_folder_ids: Optional[str] = None,  # Add direct parameter for folder_ids
        folder_id: Optional[str] = None,  # Allow both field names
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Freshdesk Knowledge Base connector.
        
        Args:
            freshdesk_folder_id: The ID of the folder to fetch articles from
            freshdesk_domain: Freshdesk domain (e.g., "company.freshdesk.com")
            freshdesk_api_key: API key for authentication
            freshdesk_portal_url: Optional URL for agent portal links
            freshdesk_portal_id: Optional ID for agent portal links
            batch_size: Number of documents to process in each batch
            connector_specific_config: Configuration specific to this connector
        """
        self.batch_size = batch_size
        self.api_key = freshdesk_api_key
        self.domain = freshdesk_domain
        self.password = "X"  # Freshdesk uses API key as username, 'X' as password
        
        logger.debug(f"Initializing Freshdesk KB connector with domain: {freshdesk_domain}")
        
        # Store connector_specific_config for later use
        self.connector_specific_config = connector_specific_config

        # Collect potential folder IDs from all possible sources
        # First, check direct parameters
        self.folder_id = freshdesk_folder_id or folder_id
        self.folder_ids: Optional[str | List[str]] = freshdesk_folder_ids
        
        # Then check connector_specific_config
        if connector_specific_config:
            logger.info(
                f"connector_specific_config keys: {list(connector_specific_config.keys())}"
            )
            
            # Check for single folder ID
            if not self.folder_id and "freshdesk_folder_id" in connector_specific_config:
                self.folder_id = connector_specific_config.get("freshdesk_folder_id")
                logger.info(
                    f"Using folder_id from connector_specific_config['freshdesk_folder_id']: "
                    f"{self.folder_id}"
                )
                
            if not self.folder_id and "folder_id" in connector_specific_config:
                self.folder_id = connector_specific_config.get("folder_id")
                logger.info(
                    f"Using folder_id from connector_specific_config['folder_id']: "
                    f"{self.folder_id}"
                )
                
            # Check for multi-folder configuration
            if not self.folder_ids and "freshdesk_folder_ids" in connector_specific_config:
                folder_ids_value = connector_specific_config.get("freshdesk_folder_ids")
                if isinstance(folder_ids_value, list):
                    self.folder_ids = folder_ids_value
                    logger.info(f"Using folder_ids (list) from connector_specific_config: {self.folder_ids}")
                elif isinstance(folder_ids_value, str):
                    self.folder_ids = folder_ids_value  # Store as string, will be parsed in load_from_state/poll_source
                    logger.info(f"Using folder_ids (string) from connector_specific_config: {self.folder_ids}")
        
        logger.debug(f"Connector initialized with folder_id: {self.folder_id}")
        
        # Optional portal params
        self.portal_url = freshdesk_portal_url
        if (
            not self.portal_url
            and connector_specific_config
            and "freshdesk_portal_url" in connector_specific_config
        ):
            self.portal_url = connector_specific_config.get("freshdesk_portal_url")
            
        self.portal_id = freshdesk_portal_id
        if (
            not self.portal_id
            and connector_specific_config
            and "freshdesk_portal_id" in connector_specific_config
        ):
            self.portal_id = connector_specific_config.get("freshdesk_portal_id")
        
        self.headers = {"Content-Type": "application/json"}
        self.base_url = f"https://{self.domain}/api/v2" if self.domain else None
        self.auth = (self.api_key, self.password) if self.api_key else None

    def load_credentials(self, credentials: dict[str, str | int]) -> None:
        """Loads Freshdesk API credentials and configuration."""
        api_key = credentials.get("freshdesk_api_key")
        domain = credentials.get("freshdesk_domain")
        portal_url = credentials.get("freshdesk_portal_url")  # For constructing agent URLs
        portal_id = credentials.get("freshdesk_portal_id")    # For constructing agent URLs
        
        # Check credentials
        if not all(isinstance(cred, str) for cred in [domain, api_key] if cred is not None):
            missing = [
                name for name, val in {
                    "domain": domain, "api_key": api_key,
                }.items() if not isinstance(val, str)
            ]
            raise ConnectorMissingCredentialError(
                f"Required Freshdesk KB credentials must be strings. "
                f"Missing/invalid: {missing}"
            )

        self.api_key = str(api_key)
        self.domain = str(domain)
        # Handle optional parameters
        self.portal_url = str(portal_url) if portal_url is not None else None
        self.portal_id = str(portal_id) if portal_id is not None else None
        self.base_url = f"https://{self.domain}/api/v2"
        self.auth = (self.api_key, self.password)
        
        # Check for folder IDs in the credentials (will be present for new configuration format)
        if "freshdesk_folder_ids" in credentials:
            folder_ids_value = credentials.get("freshdesk_folder_ids")
            if folder_ids_value:
                self.folder_ids = str(folder_ids_value)
                logger.info(
                    f"Found folder_ids in credentials: {self.folder_ids}"
                )
        
        # Also check for single folder ID (backward compatibility)
        if "freshdesk_folder_id" in credentials:
            folder_id_value = credentials.get("freshdesk_folder_id")
            if folder_id_value:
                self.folder_id = str(folder_id_value)
                logger.info(
                    f"Found single folder_id in credentials: {self.folder_id}"
                )
        
        logger.debug(f"Credentials loaded for domain: {self.domain}")

    def validate_connector_settings(self) -> None:
        """
        Validate connector settings by testing API connectivity.
        """
        # Critical validation - check for domain and API key
        if not self.domain:
            logger.error(
                "CRITICAL ERROR: Missing Freshdesk domain - check credentials!"
            )
            raise ConnectorMissingCredentialError(
                "Missing required Freshdesk domain in credentials"
            )
            
        if not self.api_key:
            logger.error(
                "CRITICAL ERROR: Missing Freshdesk API key - check credentials!"
            )
            raise ConnectorMissingCredentialError(
                "Missing required Freshdesk API key in credentials"
            )

        logger.debug("Validating connector settings")
            
        # Collect all configured folder IDs for validation
        folder_ids = []
        
        # Check if we have a single folder_id
        if hasattr(self, 'folder_id') and self.folder_id:
            folder_ids.append(self.folder_id)
            logger.info(f"Found folder_id: {self.folder_id}")
        
        # Check for folder_ids in class properties or connector_specific_config
        if hasattr(self, 'folder_ids'):
            if isinstance(self.folder_ids, list):
                folder_ids.extend(self.folder_ids)
            elif isinstance(self.folder_ids, str):
                parsed_ids = [fid.strip() for fid in self.folder_ids.split(',') if fid.strip()]
                folder_ids.extend(parsed_ids)
        
        # Also check connector_specific_config directly
        if self.connector_specific_config and "freshdesk_folder_ids" in self.connector_specific_config:
            folder_ids_value = self.connector_specific_config.get("freshdesk_folder_ids")
            if isinstance(folder_ids_value, list):
                folder_ids.extend(folder_ids_value)
            elif isinstance(folder_ids_value, str):
                parsed_ids = [fid.strip() for fid in folder_ids_value.split(',') if fid.strip()]
                folder_ids.extend(parsed_ids)
        
        # We need at least one folder ID for validation
        if not folder_ids:
            # Emergency fallback: Check if freshdesk_folder_ids exists in connector_specific_config
            if hasattr(self, "connector_specific_config") and self.connector_specific_config:
                if "freshdesk_folder_ids" in self.connector_specific_config:
                    folder_ids_value = self.connector_specific_config.get(
                        "freshdesk_folder_ids"
                    )
                    logger.info(
                        f"Using freshdesk_folder_ids directly from "
                        f"connector_specific_config: {folder_ids_value}"
                    )
                    if isinstance(folder_ids_value, str) and folder_ids_value.strip():
                        # Directly use the first ID from the string for validation
                        folder_id = folder_ids_value.split(",")[0].strip()
                        if folder_id:
                            folder_ids.append(folder_id)
                            # Also set as the folder_id attribute for backward compatibility
                            self.folder_id = folder_id
                            logger.info(
                                f"Emergency fallback: Using first ID from "
                                f"freshdesk_folder_ids: {folder_id}"
                            )
            
            # Final check - if still no folder IDs, raise error
            if not folder_ids:
                logger.error("No folder IDs found in connector settings")
                raise ConnectorMissingCredentialError(
                    "Missing folder ID(s) in connector settings. Please configure "
                    "at least one folder ID in the Freshdesk KB 'Folder IDs' field."
                )
            
        # Use the first folder ID for validation
        validation_folder_id = folder_ids[0]
        logger.info(
            f"Using folder ID {validation_folder_id} for validation "
            f"(out of {len(folder_ids)} configured folders)"
        )
        
        logger.info(
            f"Validating Freshdesk KB connector for {len(folder_ids)} folder(s)"
        )
        
        response = None
        try:
            # Test API by trying to fetch one article from the validation folder
            url = f"{self.base_url}/solutions/folders/{validation_folder_id}/articles"
            params = {"page": 1, "per_page": 1}
            
            logger.info(f"Making validation request to: {url}")
            response = requests.get(url, auth=self.auth, headers=self.headers, params=params)
            
            # Log the response for debugging
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    logger.info(
                        f"Validation successful - got {len(data)} articles in response"
                    )
                else:
                    logger.warning(
                        f"Unexpected response format: {type(data)}"
                    )
            
            response.raise_for_status()
            logger.info(
                f"Successfully validated Freshdesk KB connector for folder "
                f"{validation_folder_id}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to validate Freshdesk KB connector: {e}")
            if response is not None:
                logger.error(f"Response: {response.text}")
                logger.error(f"Status code: {response.status_code}")
            else:
                logger.error("Response: No response")
            raise ConnectorMissingCredentialError(
                f"Could not connect to Freshdesk API: {e}"
            )

    def _make_api_request(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Makes a GET request to the Freshdesk API with rate limit handling."""
        if not self.auth:
            raise ConnectorMissingCredentialError(
                "Freshdesk KB credentials not loaded."
            )
        
        # Verify the URL doesn't have duplicated domains (which could cause SSL errors)
        if ".freshdesk.com.freshdesk.com" in url:
            url = url.replace(".freshdesk.com.freshdesk.com", ".freshdesk.com")
            logger.warning(
                f"Fixed malformed URL containing duplicate domain: {url}"
            )
        
        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = requests.get(
                    url, auth=self.auth, headers=self.headers, params=params
                )
                response.raise_for_status()

                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        f"Rate limit exceeded. Retrying after {retry_after} seconds."
                    )
                    time.sleep(retry_after)
                    continue
                
                return response.json()
            except requests.exceptions.HTTPError as e:
                error_msg = f"HTTP error: {e}"
                if response is not None:
                    error_msg += f" - {response.text}"
                error_msg += f" for URL {url} with params {params}"
                logger.error(error_msg)
                return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e} for URL {url}")
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                else:
                    return None
        return None
        
    def list_available_folders(self) -> List[Dict[str, Any]]:
        """Lists all available Knowledge Base folders from Freshdesk.
        
        Returns a list of folder details that can be used for configuration.
        """
        if not self.base_url:
            raise ConnectorMissingCredentialError(
                "Freshdesk KB connector not properly configured (base_url missing)."
            )
        
        all_folders = []
        
        try:
            # First fetch all solution categories
            categories_url = f"{self.base_url}/solutions/categories"
            categories = self._make_api_request(categories_url)
            
            if not categories or not isinstance(categories, list):
                logger.error(
                    "Failed to fetch solution categories or unexpected response format"
                )
                return []
            
            # For each category, get its folders
            logger.info(f"Found {len(categories)} solution categories")
            for category in categories:
                category_id = category.get("id")
                category_name = category.get("name", "Unknown")
                
                if not category_id:
                    continue
                
                # Fetch folders for this category
                folders_url = f"{self.base_url}/solutions/categories/{category_id}/folders"
                folders = self._make_api_request(folders_url)
                
                if not folders or not isinstance(folders, list):
                    logger.warning(
                    f"Failed to fetch folders for category {category_id} or empty response"
                )
                    continue
                
                logger.info(f"Found {len(folders)} folders in category '{category_name}'")
                
                # Add category context to each folder
                for folder in folders:
                    folder["category_name"] = category_name
                    all_folders.append(folder)
                
                # Respect rate limits
                time.sleep(1)
            
            logger.info(f"Total folders found: {len(all_folders)}")
            return all_folders
            
        except Exception as e:
            logger.error(f"Error listing available folders: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def _fetch_articles_from_folder(
        self, folder_id: str, updated_since: Optional[datetime] = None
    ) -> Iterator[List[dict]]:
        """Fetches solution articles from a specific folder, handling pagination.
        
        Filters by 'updated_since' if provided.
        """
        if not self.base_url or not folder_id:
            raise ConnectorMissingCredentialError(
                "Freshdesk KB connector not properly configured "
                "(base_url or folder_id missing)."
            )

        page = 1
        while True:
            url = f"{self.base_url}/solutions/folders/{folder_id}/articles"
            params: dict[str, Any] = {"page": page, "per_page": 30}

            logger.info(
                f"Fetching articles from Freshdesk KB folder {folder_id}, page {page}..."
            )
            article_batch = self._make_api_request(url, params)

            if article_batch is None:  # Error occurred
                logger.error(
                    f"Failed to fetch articles for folder {folder_id}, page {page}."
                )
                break
            
            if not isinstance(article_batch, list):
                logger.error(
                    f"Unexpected API response format for articles: "
                    f"{type(article_batch)}. Expected list."
                )
                break

            if not article_batch:  # No more articles
                logger.info(
                    f"No more articles found for folder {folder_id} on page {page}."
                )
                break
            
            # If updated_since is provided, filter locally
            if updated_since:
                filtered_batch = []
                for article in article_batch:
                    if article.get("updated_at"):
                        article_updated_at = datetime.fromisoformat(
                            article["updated_at"].replace("Z", "+00:00")
                        )
                        if article_updated_at >= updated_since:
                            filtered_batch.append(article)
                
                if filtered_batch:
                    logger.info(f"Fetched {len(filtered_batch)} articles updated since {updated_since.isoformat()} from folder {folder_id}, page {page}.")
                    yield filtered_batch
            else:
                logger.info(f"Fetched {len(article_batch)} articles from folder {folder_id}, page {page}.")
                yield article_batch

            if len(article_batch) < params["per_page"]:
                logger.info(f"Last page reached for folder {folder_id}.")
                break
            
            page += 1
            time.sleep(1)  # Basic rate limiting

    def _process_articles(
        self, folder_ids: List[str], start_time: Optional[datetime] = None
    ) -> GenerateDocumentsOutput:
        """Process articles from multiple folders, converting them to Onyx Documents.
        
        Accepts a list of folder IDs to fetch from.
        """
        if not self.domain:
            raise ConnectorMissingCredentialError(
                "Freshdesk KB domain not loaded."
            )
            
        
        # Handle case where a single folder ID string is passed
        if isinstance(folder_ids, str):
            folder_ids = [folder_ids]
            
        # Make sure we have at least one folder ID
        if not folder_ids:
            logger.error("No folder IDs provided for processing")
            raise ValueError("No folder IDs provided for processing")
            
        logger.info(
            f"Processing articles from {len(folder_ids)} folders: {folder_ids}"
        )
        
        # Use portal_url and portal_id if available, otherwise use None
        portal_url = self.portal_url if self.portal_url else None
        portal_id = self.portal_id if self.portal_id else None
        
        article_count = 0
        
        try:
            # Process each folder one by one
            for folder_id in folder_ids:
                logger.info(f"Processing folder ID: {folder_id}")
                folder_article_count = 0
                
                # Process articles in batches for this folder
                for article_list_from_api in self._fetch_articles_from_folder(
                    folder_id, start_time
                ):
                    if not article_list_from_api:
                        logger.info(
                            f"Received empty article batch from folder {folder_id} - skipping"
                        )
                        continue
                    
                    logger.info(
                        f"Processing batch of {len(article_list_from_api)} articles "
                        f"from folder {folder_id}"
                    )
                    folder_article_count += len(article_list_from_api)
                    article_count += len(article_list_from_api)
                    
                    # Process each batch of articles separately to avoid any cross-batch dependencies
                    current_batch = []
                    
                    for article_data in article_list_from_api:
                        try:
                            doc = _create_doc_from_article(article_data, self.domain, portal_url, portal_id)
                            current_batch.append(doc)
                        except Exception as e:
                            article_id = article_data.get("id", "UNKNOWN")
                            logger.error(
                                f"Failed to create document for article {article_id}: {e}"
                            )
                            # Skip this article and continue with others
                    
                    # Yield this batch immediately
                    if current_batch:
                        yield current_batch
                
                logger.info(f"Completed processing folder {folder_id} - {folder_article_count} articles indexed")
            
            logger.info(f"Completed processing {article_count} articles from {len(folder_ids)} folders")
            
        except Exception as e:
            logger.error(f"Critical error in article processing: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all solution articles from the configured folders."""
        # Get folder_ids from connector config
        folder_ids = []
        
        # Check if we have a single folder_id or multiple folder_ids in the configuration
        if hasattr(self, 'folder_id') and self.folder_id:
            # Single folder ID provided directly
            folder_ids.append(self.folder_id)
        
        # Check for folder_ids in connector_specific_config and class attributes
        if hasattr(self, 'connector_specific_config') and self.connector_specific_config:
            # Check for freshdesk_folder_ids in connector_specific_config
            if 'freshdesk_folder_ids' in self.connector_specific_config:
                folder_ids_value = self.connector_specific_config.get('freshdesk_folder_ids')
                if isinstance(folder_ids_value, list):
                    folder_ids.extend(folder_ids_value)
                elif isinstance(folder_ids_value, str):
                    folder_ids.extend([fid.strip() for fid in folder_ids_value.split(',') if fid.strip()])
                logger.info(f"Using folder_ids from connector_specific_config['freshdesk_folder_ids']: {folder_ids}")
        
        # Also check if folder_ids was set as a class attribute
        if hasattr(self, 'folder_ids'):
            if isinstance(self.folder_ids, list):
                # Multiple folder IDs provided as a list
                folder_ids.extend(self.folder_ids)
                logger.info(f"Using folder_ids from self.folder_ids (list): {self.folder_ids}")
            elif isinstance(self.folder_ids, str):
                # Multiple folder IDs provided as a comma-separated string
                parsed_ids = [folder_id.strip() for folder_id in self.folder_ids.split(',') if folder_id.strip()]
                folder_ids.extend(parsed_ids)
                logger.info(f"Using folder_ids from self.folder_ids (string): parsed as {parsed_ids}")
            
        if not folder_ids:
            raise ConnectorMissingCredentialError("No Freshdesk KB folder_id(s) configured for load_from_state.")
            
        # Double check credentials before starting indexing
        if not self.domain or not self.api_key:
            logger.error(
                f"CRITICAL ERROR: Missing credentials in load_from_state! "
                f"domain={self.domain}, api_key_present={'Yes' if self.api_key else 'No'}"
            )
            logger.error(f"Base URL: {self.base_url}, Auth: {bool(self.auth)}")
            raise ConnectorMissingCredentialError("Missing required Freshdesk credentials for indexing")
            
        logger.info(f"Loading all solution articles from {len(folder_ids)} Freshdesk KB folders: {folder_ids}")
        logger.info(f"Using domain: {self.domain}")
        
        # Explicitly log that we're starting to yield documents
        logger.info(f"Starting to yield documents from Freshdesk KB folders")
        yield from self._process_articles(folder_ids)

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        """
        Polls for solution articles updated within the given time range.
        """
        # Get folder_ids from connector config
        folder_ids = []
        
        # Check if we have a single folder_id or multiple folder_ids in the configuration
        if hasattr(self, 'folder_id') and self.folder_id:
            # Single folder ID provided directly
            folder_ids.append(self.folder_id)
        
        # Check for folder_ids in connector_specific_config and class attributes
        if hasattr(self, 'connector_specific_config') and self.connector_specific_config:
            # Check for freshdesk_folder_ids in connector_specific_config
            if 'freshdesk_folder_ids' in self.connector_specific_config:
                folder_ids_value = self.connector_specific_config.get('freshdesk_folder_ids')
                if isinstance(folder_ids_value, list):
                    folder_ids.extend(folder_ids_value)
                elif isinstance(folder_ids_value, str):
                    folder_ids.extend([fid.strip() for fid in folder_ids_value.split(',') if fid.strip()])
                logger.info(f"Poll: Using folder_ids from connector_specific_config['freshdesk_folder_ids']: {folder_ids}")
        
        # Also check if folder_ids was set as a class attribute
        if hasattr(self, 'folder_ids'):
            if isinstance(self.folder_ids, list):
                # Multiple folder IDs provided as a list
                folder_ids.extend(self.folder_ids)
                logger.info(f"Poll: Using folder_ids from self.folder_ids (list): {self.folder_ids}")
            elif isinstance(self.folder_ids, str):
                # Multiple folder IDs provided as a comma-separated string
                parsed_ids = [folder_id.strip() for folder_id in self.folder_ids.split(',') if folder_id.strip()]
                folder_ids.extend(parsed_ids)
                logger.info(f"Poll: Using folder_ids from self.folder_ids (string): parsed as {parsed_ids}")
            
        if not folder_ids:
            raise ConnectorMissingCredentialError("No Freshdesk KB folder_id(s) configured for poll_source.")
            
        # Double check credentials before starting polling
        if not self.domain or not self.api_key:
            logger.error(
                f"CRITICAL ERROR: Missing credentials in poll_source! "
                f"domain={self.domain}, api_key_present={'Yes' if self.api_key else 'No'}"
            )
            logger.error(f"Base URL: {self.base_url}, Auth: {bool(self.auth)}")
            raise ConnectorMissingCredentialError("Missing required Freshdesk credentials for polling")
        
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        
        logger.info(f"Polling {len(folder_ids)} Freshdesk KB folders for updates since {start_datetime.isoformat()}")
        logger.info(f"Using domain: {self.domain}, folders: {folder_ids}")
        yield from self._process_articles(folder_ids, start_datetime)

    def _get_slim_documents_for_article_batch(self, articles: List[Dict[str, Any]]) -> List[SlimDocument]:
        """Convert a batch of articles to SlimDocuments."""
        slim_docs = []
        for article in articles:
            article_id = article.get("id")
            if article_id:
                # All we need is the ID - no permissions data needed for this connector
                slim_docs.append(
                    SlimDocument(
                        id=_FRESHDESK_KB_ID_PREFIX + str(article_id)
                    )
                )
        return slim_docs

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """
        Retrieves all document IDs for pruning purposes.
        """
        # Get folder_ids using same logic as load_from_state and poll_source
        folder_ids = []
        
        # Check if we have a single folder_id or multiple folder_ids in the configuration
        if hasattr(self, 'folder_id') and self.folder_id:
            # Single folder ID provided directly
            folder_ids.append(self.folder_id)
        
        # Check for folder_ids in connector_specific_config and class attributes
        if hasattr(self, 'connector_specific_config') and self.connector_specific_config:
            # Check for freshdesk_folder_ids in connector_specific_config
            if 'freshdesk_folder_ids' in self.connector_specific_config:
                folder_ids_value = self.connector_specific_config.get('freshdesk_folder_ids')
                if isinstance(folder_ids_value, list):
                    folder_ids.extend(folder_ids_value)
                elif isinstance(folder_ids_value, str):
                    folder_ids.extend([fid.strip() for fid in folder_ids_value.split(',') if fid.strip()])
        
        # Also check if folder_ids was set as a class attribute
        if hasattr(self, 'folder_ids'):
            if isinstance(self.folder_ids, list):
                folder_ids.extend(self.folder_ids)
            elif isinstance(self.folder_ids, str):
                parsed_ids = [folder_id.strip() for folder_id in self.folder_ids.split(',') if folder_id.strip()]
                folder_ids.extend(parsed_ids)
            
        if not folder_ids:
            raise ConnectorMissingCredentialError("No Freshdesk KB folder_id(s) configured for slim document retrieval.")
        
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        
        # Process each folder
        for folder_id in folder_ids:
            logger.info(f"Retrieving slim documents from folder {folder_id}")
            
            slim_batch: List[SlimDocument] = []
            for article_batch in self._fetch_articles_from_folder(folder_id, start_datetime):
                # Convert to slim documents
                new_slim_docs = self._get_slim_documents_for_article_batch(article_batch)
                slim_batch.extend(new_slim_docs)
                
                # Progress callback if provided
                if callback:
                    callback.progress("retrieve_all_slim_documents", len(new_slim_docs))
                
                if len(slim_batch) >= self.batch_size:
                    logger.info(f"Yielding batch of {len(slim_batch)} slim documents from folder {folder_id}")
                    yield slim_batch
                    slim_batch = []
            
            if slim_batch:
                logger.info(f"Yielding final batch of {len(slim_batch)} slim documents from folder {folder_id}")
                yield slim_batch
        
        logger.info(f"Completed retrieval of slim documents from {len(folder_ids)} folders")
