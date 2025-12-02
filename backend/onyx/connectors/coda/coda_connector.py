import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput, LoadConnector
from onyx.connectors.models import Document, Section
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CodaConnector(LoadConnector):
    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.base_url = "https://coda.io/apis/v1"
        self.coda_api_token: Optional[str] = None
        self.session = requests.Session()
        
        # Set up session with retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        """Load and validate Coda API credentials."""
        self.coda_api_token = credentials["coda_api_token"]
        self.headers = {
            "Authorization": f"Bearer {self.coda_api_token}",
            "Content-Type": "application/json",
        }
        
        # Test the connection
        try:
            self._make_request(f"{self.base_url}/docs", {"limit": 1})
            return None
        except Exception as e:
            logger.error(f"Failed to validate Coda credentials: {e}")
            raise ValueError(f"Invalid Coda API token: {e}")

    def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Coda API with error handling."""
        if not self.coda_api_token:
            raise ValueError("Coda API token not set. Call load_credentials first.")
            
        try:
            response = self.session.get(url, headers=self.headers, params=params or {})
            
            if response.status_code == 429:
                logger.warning("Rate limited by Coda API, waiting...")
                time.sleep(2)
                response = self.session.get(url, headers=self.headers, params=params or {})
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {e}")
            raise

    def _get_all_docs(self) -> List[Dict[str, Any]]:
        """Fetch all documents from the user's Coda workspace."""
        url = f"{self.base_url}/docs"
        params = {"limit": 100}
        all_docs = []
        
        while url:
            logger.info(f"Fetching docs from Coda API")
            response_data = self._make_request(url, params)
            
            docs = response_data.get("items", [])
            all_docs.extend(docs)
            
            # Handle pagination
            next_page_token = response_data.get("nextPageToken")
            if next_page_token:
                params["pageToken"] = next_page_token
                url = f"{self.base_url}/docs"
            else:
                url = None
                
        logger.info(f"Found {len(all_docs)} total documents")
        return all_docs

    def _get_doc_pages(self, doc_id: str) -> List[Dict[str, Any]]:
        """Fetch all pages for a given document."""
        url = f"{self.base_url}/docs/{doc_id}/pages"
        params = {"limit": 100}
        all_pages = []
        
        while url:
            response_data = self._make_request(url, params)
            
            pages = response_data.get("items", [])
            all_pages.extend(pages)
            
            # Handle pagination
            next_page_token = response_data.get("nextPageToken")
            if next_page_token:
                params["pageToken"] = next_page_token
                url = f"{self.base_url}/docs/{doc_id}/pages"
            else:
                url = None
                
        return all_pages

    def _convert_page_to_document(self, page: Dict[str, Any], doc: Dict[str, Any]) -> Document:
        """Convert a Coda page to an Onyx Document."""
        
        # Extract page content
        page_name = page.get("name", "Untitled Page")
        page_id = page.get("id", "")
        
        # Get page content
        content_sections = []
        
        # Add page title as first section
        if page_name:
            content_sections.append(
                Section(
                    text=page_name,
                    link=page.get("browserLink"),
                )
            )
        
        # Add a content section (Coda API doesn't provide full content via pages endpoint)
        content_text = f"Page from Coda document: {doc.get('name', '')}\nPage: {page_name}"
        content_sections.append(
            Section(
                text=content_text,
                link=page.get("browserLink"),
            )
        )

        # Create document metadata
        metadata: Dict[str, Any] = {
            "doc_id": doc.get("id"),
            "doc_name": doc.get("name"),
            "page_id": page_id,
            "page_name": page_name,
            "created_at": page.get("createdAt"),
            "updated_at": page.get("updatedAt"),
            "owner": doc.get("owner", {}).get("name"),
            "browser_link": page.get("browserLink"),
        }

        # Create unique document ID
        doc_id_clean = doc.get("id", "").replace("-", "_")
        page_id_clean = page_id.replace("-", "_")
        unique_id = f"coda_{doc_id_clean}_{page_id_clean}"

        return Document(
            id=unique_id,
            sections=content_sections,
            source=DocumentSource.CODA,
            semantic_identifier=f"{doc.get('name', 'Untitled')} - {page_name}",
            metadata=metadata,
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Main method to fetch and convert Coda documents."""
        logger.info("Starting Coda document sync...")
        
        if not self.coda_api_token:
            raise ValueError("Coda API token not loaded. Call load_credentials first.")
        
        # Get all documents
        docs = self._get_all_docs()
        
        documents = []
        
        for doc in docs:
            try:
                logger.info(f"Processing document: {doc.get('name', 'Unknown')}")
                
                # Get pages for this document
                pages = self._get_doc_pages(doc["id"])
                
                if pages:
                    # Convert each page to a document
                    for page in pages:
                        try:
                            document = self._convert_page_to_document(page, doc)
                            documents.append(document)
                        except Exception as e:
                            logger.error(f"Error converting page {page.get('id', 'unknown')}: {e}")
                            continue
                else:
                    logger.info(f"Document {doc.get('name')} has no pages, skipping...")
                        
            except Exception as e:
                logger.error(f"Error processing document {doc.get('id', 'unknown')}: {e}")
                continue
        
        logger.info(f"Successfully processed {len(documents)} documents from Coda")
        
        # Yield documents in batches
        for i in range(0, len(documents), self.batch_size):
            batch = documents[i:i + self.batch_size]
            yield batch