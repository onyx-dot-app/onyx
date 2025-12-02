import time
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CodaConnectorTest:
    def __init__(self, coda_api_token: str):
        self.coda_api_token = coda_api_token
        self.base_url = "https://coda.io/apis/v1"
        
        # Set up session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.headers = {
            "Authorization": f"Bearer {self.coda_api_token}",
            "Content-Type": "application/json",
        }

    def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Coda API with error handling."""
        try:
            response = self.session.get(url, headers=self.headers, params=params or {})
            
            if response.status_code == 429:
                print("Rate limited by Coda API, waiting...")
                time.sleep(2)
                response = self.session.get(url, headers=self.headers, params=params or {})
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {e}")
            raise

    def get_all_docs(self) -> List[Dict[str, Any]]:
        """Fetch all documents from the user's Coda workspace."""
        url = f"{self.base_url}/docs"
        params = {"limit": 100}
        all_docs = []
        
        while url:
            print(f"Fetching docs from: {url}")
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
                
        print(f"Found {len(all_docs)} total documents")
        return all_docs

    def get_doc_pages(self, doc_id: str) -> List[Dict[str, Any]]:
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

    def test_connector(self):
        """Test the connector functionality."""
        print("Testing Coda Connector...")
        print("=" * 50)
        
        # Test 1: Get all docs
        print("\n1. Fetching documents...")
        docs = self.get_all_docs()
        
        if not docs:
            print("❌ No documents found! Make sure you have docs in your Coda workspace.")
            return
        
        print(f"✅ Found {len(docs)} documents:")
        for doc in docs[:5]:  # Show first 5
            print(f"   - {doc.get('name', 'Untitled')}")
        
        # Test 2: Get pages from first doc
        first_doc = docs[0]
        print(f"\n2. Fetching pages from '{first_doc.get('name')}'...")
        pages = self.get_doc_pages(first_doc['id'])
        
        print(f"✅ Found {len(pages)} pages:")
        for page in pages[:5]:  # Show first 5
            print(f"   - {page.get('name', 'Untitled Page')}")
        
        # Test 3: Show document structure
        print(f"\n3. Document structure analysis:")
        total_docs = len(docs)
        total_pages = 0
        
        for doc in docs:
            pages = self.get_doc_pages(doc['id'])
            total_pages += len(pages)
            print(f"   📄 {doc.get('name', 'Untitled')}: {len(pages)} pages")
        
        print(f"\n📊 Summary:")
        print(f"   Total documents: {total_docs}")
        print(f"   Total pages: {total_pages}")
        print(f"   Documents that would be created: {total_pages if total_pages > 0 else total_docs}")
        
        print("\n✅ Connector test completed successfully!")
        return True


if __name__ == "__main__":
    # Test with your API token
    api_token = "001a1ae7-17d6-44af-b6d3-314b7e95ec13"
    
    connector = CodaConnectorTest(coda_api_token=api_token)
    connector.test_connector()