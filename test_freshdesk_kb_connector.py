#!/usr/bin/env python
"""
Standalone test script for the Freshdesk Knowledge Base connector.

This script allows you to test the connector functionality without running
the full Onyx system. Run it directly to validate the connector against your
Freshdesk instance.

Usage:
    python test_freshdesk_kb_connector.py

You'll be prompted to enter your Freshdesk credentials, or you can set them
as environment variables:
    - FRESHDESK_DOMAIN
    - FRESHDESK_API_KEY
    - FRESHDESK_FOLDER_ID
    - FRESHDESK_PORTAL_URL (optional)
    - FRESHDESK_PORTAL_ID (optional)
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import requests
from bs4 import BeautifulSoup
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
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


class Document:
    """Simple document class to represent Onyx Document objects"""
    def __init__(
        self,
        id: str,
        sections: List[Dict[str, str]],
        source: str,
        semantic_identifier: str,
        metadata: Dict[str, Any],
        doc_updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.sections = sections
        self.source = source
        self.semantic_identifier = semantic_identifier
        self.metadata = metadata
        self.doc_updated_at = doc_updated_at


def clean_html_content(html_content: str) -> str:
    """
    Cleans HTML content, extracting plain text.
    Uses BeautifulSoup to parse HTML and get text.
    """
    if not html_content:
        return ""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        text_parts = [p.get_text(separator=" ", strip=True) for p in soup.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])]
        if not text_parts:
            return soup.get_text(separator=" ", strip=True)
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Error cleaning HTML with BeautifulSoup: {e}")
        return html_content


def create_metadata_from_article(article: dict, domain: str, portal_url: str, portal_id: str) -> dict:
    """
    Creates a metadata dictionary from a Freshdesk solution article.
    """
    metadata: Dict[str, Any] = {}
    article_id = article.get("id")

    for key, value in article.items():
        if key not in _SOLUTION_ARTICLE_FIELDS_TO_INCLUDE:
            continue
        if value is None or (isinstance(value, list) and not value):  # Skip None or empty lists
            continue
        metadata[key] = value
    
    # Construct URLs
    if article_id:
        # Agent URL (the one with portalId)
        if portal_url and portal_id:
            portal_base = portal_url.rstrip('/')
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


def create_doc_from_article(article: dict, domain: str, portal_url: str, portal_id: str) -> Document:
    """
    Creates a Document from a Freshdesk solution article.
    """
    article_id = article.get("id")
    title = article.get("title", "Untitled Article")
    html_description = article.get("description", "")
    
    # Clean HTML content
    text_content = clean_html_content(html_description)

    metadata = create_metadata_from_article(article, domain, portal_url, portal_id)
    
    # Use agent_url as the primary link for the section if available, else public_url
    link = metadata.get("agent_url") or metadata.get("public_url") or f"https://{domain}/a/solutions/articles/{article_id}"

    return Document(
        id=_FRESHDESK_KB_ID_PREFIX + str(article_id) if article_id else _FRESHDESK_KB_ID_PREFIX + "UNKNOWN",
        sections=[
            {
                "link": link,
                "text": text_content,
            }
        ],
        source="freshdesk_kb",
        semantic_identifier=title,
        metadata=metadata,
        doc_updated_at=datetime.fromisoformat(article["updated_at"].replace("Z", "+00:00")) if article.get("updated_at") else datetime.now(timezone.utc),
    )


class FreshdeskKBConnector:
    """
    Connector for fetching Freshdesk Knowledge Base (Solution Articles) from a specific folder.
    """
    def __init__(self, batch_size: int = 30) -> None:
        self.batch_size = batch_size
        self.api_key: Optional[str] = None
        self.domain: Optional[str] = None
        self.password: Optional[str] = "X"  # Freshdesk uses API key as username, 'X' as password
        self.folder_id: Optional[str] = None
        self.portal_url: Optional[str] = None
        self.portal_id: Optional[str] = None
        self.base_url: Optional[str] = None
        self.auth: Optional[tuple] = None
        self.headers = {"Content-Type": "application/json"}

    def load_credentials(self, credentials: Dict[str, str]) -> None:
        """Loads Freshdesk API credentials and configuration."""
        api_key = credentials.get("freshdesk_api_key")
        domain = credentials.get("freshdesk_domain")
        folder_id = credentials.get("freshdesk_folder_id")
        portal_url = credentials.get("freshdesk_portal_url")  # For constructing agent URLs
        portal_id = credentials.get("freshdesk_portal_id")    # For constructing agent URLs
        
        # Check credentials
        if not all(cred and cred.strip() for cred in [domain, api_key, folder_id] if cred is not None):
            raise ValueError(
                "Required Freshdesk KB credentials missing. Need: domain, api_key, folder_id"
            )

        self.api_key = str(api_key)
        self.domain = str(domain)
        self.folder_id = str(folder_id)
        # Handle optional parameters
        self.portal_url = str(portal_url) if portal_url is not None else None
        self.portal_id = str(portal_id) if portal_id is not None else None
        self.base_url = f"https://{self.domain}/api/v2"
        self.auth = (self.api_key, self.password)

    def validate_connector_settings(self) -> None:
        """
        Validate connector settings by testing API connectivity.
        """
        if not self.api_key or not self.domain or not self.folder_id:
            raise ValueError(
                "Missing required credentials for FreshdeskKnowledgeBaseConnector"
            )
        
        try:
            # Test API by trying to fetch one article from the folder
            url = f"{self.base_url}/solutions/folders/{self.folder_id}/articles"
            params = {"page": 1, "per_page": 1}
            response = requests.get(url, auth=self.auth, headers=self.headers, params=params)
            response.raise_for_status()
            logger.info(f"Successfully validated Freshdesk KB connector for folder {self.folder_id}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to validate Freshdesk KB connector: {e}")
            raise ValueError(
                f"Could not connect to Freshdesk API: {e}"
            )

    def make_api_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
        """Makes a GET request to the Freshdesk API with rate limit handling."""
        if not self.auth:
            raise ValueError("Freshdesk KB credentials not loaded.")
        
        # Verify the URL doesn't have duplicated domains (which could cause SSL errors)
        if ".freshdesk.com.freshdesk.com" in url:
            url = url.replace(".freshdesk.com.freshdesk.com", ".freshdesk.com")
            logger.warning(f"Fixed malformed URL containing duplicate domain: {url}")
        
        retries = 3
        for attempt in range(retries):
            try:
                response = requests.get(url, auth=self.auth, headers=self.headers, params=params)
                response.raise_for_status()

                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limit exceeded. Retrying after {retry_after} seconds.")
                    time.sleep(retry_after)
                    continue
                
                return response.json()
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error: {e} - {response.text if 'response' in locals() else 'No response'} for URL {url} with params {params}")
                return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e} for URL {url}")
                if attempt < retries - 1:
                    logger.info(f"Retrying ({attempt + 1}/{retries})...")
                    time.sleep(5 * (attempt + 1))
                else:
                    return None
        return None

    def fetch_articles_from_folder(self, folder_id: str, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Fetches solution articles from a specific folder, handling pagination.
        Filters by 'updated_since' if provided.
        """
        if not self.base_url or not folder_id:
            raise ValueError("Freshdesk KB connector not properly configured (base_url or folder_id missing).")

        all_articles = []
        page = 1
        while True:
            url = f"{self.base_url}/solutions/folders/{folder_id}/articles"
            params: Dict[str, Any] = {"page": page, "per_page": 30}

            logger.info(f"Fetching articles from Freshdesk KB folder {folder_id}, page {page}...")
            article_batch = self.make_api_request(url, params)

            if article_batch is None:  # Error occurred
                logger.error(f"Failed to fetch articles for folder {folder_id}, page {page}.")
                break
            
            if not isinstance(article_batch, list):
                logger.error(f"Unexpected API response format for articles: {type(article_batch)}. Expected list.")
                break

            if not article_batch:  # No more articles
                logger.info(f"No more articles found for folder {folder_id} on page {page}.")
                break
            
            # If updated_since is provided, filter locally
            if updated_since:
                filtered_batch = []
                for article in article_batch:
                    if article.get("updated_at"):
                        article_updated_at = datetime.fromisoformat(article["updated_at"].replace("Z", "+00:00"))
                        if article_updated_at >= updated_since:
                            filtered_batch.append(article)
                
                if filtered_batch:
                    logger.info(f"Fetched {len(filtered_batch)} articles updated since {updated_since.isoformat()} from folder {folder_id}, page {page}.")
                    all_articles.extend(filtered_batch)
            else:
                logger.info(f"Fetched {len(article_batch)} articles from folder {folder_id}, page {page}.")
                all_articles.extend(article_batch)

            if len(article_batch) < params["per_page"]:
                logger.info(f"Last page reached for folder {folder_id}.")
                break
            
            page += 1
            time.sleep(1)  # Basic rate limiting
            
        return all_articles

    def process_articles(self, folder_id_to_fetch: str, start_time: Optional[datetime] = None) -> List[Document]:
        """
        Processes articles from a folder, converting them to Documents.
        'start_time' is for filtering articles updated since that time.
        """
        if not self.domain:
            raise ValueError("Freshdesk KB domain not loaded.")

        docs = []
        
        # Use portal_url and portal_id if available, otherwise use None
        portal_url = self.portal_url if self.portal_url else None
        portal_id = self.portal_id if self.portal_id else None
        
        articles = self.fetch_articles_from_folder(folder_id_to_fetch, start_time)
        
        for article_data in articles:
            try:
                doc = create_doc_from_article(article_data, self.domain, portal_url, portal_id)
                docs.append(doc)
            except Exception as e:
                logger.error(f"Error creating document for article ID {article_data.get('id')}: {e}")
                continue
        
        return docs

    def load_from_state(self) -> List[Document]:
        """Loads all solution articles from the configured folder."""
        if not self.folder_id:
            raise ValueError("Freshdesk KB folder_id not configured for load_from_state.")
        logger.info(f"Loading all solution articles from Freshdesk KB folder: {self.folder_id}")
        return self.process_articles(self.folder_id)

    def poll_source(self, start_time: datetime) -> List[Document]:
        """
        Polls for solution articles updated since the given time.
        """
        if not self.folder_id:
            raise ValueError("Freshdesk KB folder_id not configured for poll_source.")
        
        logger.info(f"Polling Freshdesk KB folder {self.folder_id} for updates since {start_time.isoformat()}")
        return self.process_articles(self.folder_id, start_time)


def get_input_with_default(prompt: str, default: str = "", is_password: bool = False) -> str:
    """Get user input with a default value."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
        
    if is_password:
        import getpass
        value = getpass.getpass(prompt)
    else:
        value = input(prompt)
        
    return value if value else default


def main():
    """Main function to test the Freshdesk KB connector."""
    print("\n=== Freshdesk Knowledge Base Connector Test ===\n")
    
    # Get credentials from environment or prompt user
    domain = os.environ.get("FRESHDESK_DOMAIN") or get_input_with_default("Enter your Freshdesk domain (e.g., company.freshdesk.com)")
    api_key = os.environ.get("FRESHDESK_API_KEY") or get_input_with_default("Enter your Freshdesk API key", is_password=True)
    folder_id = os.environ.get("FRESHDESK_FOLDER_ID") or get_input_with_default("Enter the folder ID to fetch articles from")
    portal_url = os.environ.get("FRESHDESK_PORTAL_URL") or get_input_with_default("Enter your portal URL (optional, e.g., https://support.company.com)")
    portal_id = os.environ.get("FRESHDESK_PORTAL_ID") or get_input_with_default("Enter your portal ID (optional)")
    
    # Initialize the connector
    connector = FreshdeskKBConnector()
    connector.load_credentials({
        "freshdesk_domain": domain,
        "freshdesk_api_key": api_key,
        "freshdesk_folder_id": folder_id,
        "freshdesk_portal_url": portal_url,
        "freshdesk_portal_id": portal_id,
    })
    
    try:
        # Validate the connector settings
        print("\nValidating connector settings...")
        connector.validate_connector_settings()
        print("✅ Connector settings validated successfully!")
        
        # Test loading all articles
        print("\nFetching all articles from the specified folder...")
        all_docs = connector.load_from_state()
        print(f"✅ Successfully fetched {len(all_docs)} articles.")
        
        # Display summary of the first 5 articles
        if all_docs:
            print("\nSummary of the first 5 articles:")
            for i, doc in enumerate(all_docs[:5]):
                print(f"\n{i+1}. {doc.semantic_identifier}")
                print(f"   ID: {doc.id}")
                print(f"   Updated: {doc.doc_updated_at.isoformat() if doc.doc_updated_at else 'Unknown'}")
                print(f"   Section count: {len(doc.sections)}")
                print(f"   Content preview: {doc.sections[0]['text'][:100]}..." if doc.sections and 'text' in doc.sections[0] else "   No content")
        
        # Test polling for recent articles (last 24 hours)
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        print(f"\nPolling for articles updated in the last 24 hours (since {one_day_ago.isoformat()})...")
        recent_docs = connector.poll_source(one_day_ago)
        print(f"✅ Found {len(recent_docs)} articles updated in the last 24 hours.")
        
        # Save results to a JSON file for inspection
        output_file = "freshdesk_kb_test_results.json"
        with open(output_file, "w") as f:
            json.dump(
                {
                    "total_articles": len(all_docs),
                    "recently_updated": len(recent_docs),
                    "sample_articles": [
                        {
                            "id": doc.id,
                            "title": doc.semantic_identifier,
                            "updated_at": doc.doc_updated_at.isoformat() if doc.doc_updated_at else None,
                            "metadata": doc.metadata,
                            # Include only the first 500 chars of content to keep the file manageable
                            "content_preview": doc.sections[0]["text"][:500] + "..." if doc.sections and "text" in doc.sections[0] else "No content"
                        }
                        for doc in all_docs[:10]  # Save the first 10 articles as samples
                    ]
                },
                f,
                indent=2,
                default=str  # Handle any non-serializable objects
            )
        print(f"\n✅ Test results saved to {output_file}")
        
        print("\n=== Test completed successfully! ===")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\n=== Test failed! ===")


if __name__ == "__main__":
    main()
