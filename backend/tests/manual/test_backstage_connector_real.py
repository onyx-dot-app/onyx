"""
Manual test for the Backstage connector against a real Backstage instance.

This test is designed to be run manually with real credentials.
It is not intended to be part of the automated test suite.

To run this test:
1. Set the environment variables for your Backstage instance:
   - BACKSTAGE_BASE_URL: The base URL of your Backstage instance
   - BACKSTAGE_CLIENT_ID: Your OAuth client ID
   - BACKSTAGE_CLIENT_SECRET: Your OAuth client secret
   - BACKSTAGE_TOKEN_ENDPOINT: Your OAuth token endpoint
   
2. Run the script from the backend directory:
   python tests/manual/test_backstage_connector_real.py
"""
import pytest
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List

# Add the parent directory to the path to allow importing onyx modules
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from onyx.connectors.backstage.connector import BackstageConnector
from onyx.connectors.models import Document

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def check_environment_variables() -> bool:
    """Check if all required environment variables are set."""
    required_vars = [
        "BACKSTAGE_BASE_URL",
        "BACKSTAGE_CLIENT_ID",
        "BACKSTAGE_CLIENT_SECRET",
        "BACKSTAGE_TOKEN_ENDPOINT",
    ]
    missing_vars = [var for var in required_vars if var not in os.environ]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please set all required environment variables before running this test.")
        return False
    return True


# def test_connector_init() -> BackstageConnector:
#     """Test initializing the connector."""
#     base_url = os.environ["BACKSTAGE_BASE_URL"]
#
#     logger.info(f"Initializing connector with base URL: {base_url}")
#     connector = BackstageConnector(
#         base_url=base_url,
#         entity_kinds=[
#             BACKSTAGE_ENTITY_KINDS.COMPONENT.value,
#             BACKSTAGE_ENTITY_KINDS.API.value,
#             BACKSTAGE_ENTITY_KINDS.SYSTEM.value,
#             # Add more entity kinds as needed
#         ],
#         batch_size=100,
#     )
#
#     return connector

@pytest.fixture
def backstage_connector(request: pytest.FixtureRequest) -> BackstageConnector:
    scroll_before_scraping = request.param
    base_url = "https://portal.services.as24.tech/"
    connector = BackstageConnector(base_url)
    return connector

@pytest.mark.parametrize("backstage_connector", [True], indirect=True)
def test_authentication(backstage_connector: BackstageConnector) -> bool:
    """Test authentication against the real Backstage instance."""
    logger.info("Testing authentication...")
    try:
        credentials = {
            "backstage_client_id": '0oac8kk59fZ7JrSLo417',
            "backstage_client_secret": 'XAlKbs3anEJeAA4C9M2yCGRrlFQTWVqReAA_-aIAzuyKTvqftObjGDxNVvnFiqA9',
            "backstage_token_endpoint": 'https://sso.autoscout24.com/oauth2/aus9wib4wxyjWgscj417/v1/token',
        }
        backstage_connector.load_credentials(credentials)
        entities = backstage_connector.get_entities_by_kind("api")
        # Print the first 5 entities
        for entity in entities[:5]:
            print(entity)
        logger.info("✓ Authentication successful")
        return True
    except Exception as e:
        logger.error(f"✗ Authentication failed: {e}")
        return False


def test_validation(connector: BackstageConnector) -> bool:
    """Test validating the connector settings."""
    logger.info("Testing connector validation...")
    try:
        connector.validate_connector_settings()
        logger.info("✓ Validation successful")
        return True
    except Exception as e:
        logger.error(f"✗ Validation failed: {e}")
        return False


def test_fetch_entities(connector: BackstageConnector) -> List[Document]:
    """Test fetching and processing entities from Backstage."""
    logger.info("Testing entity fetching...")
    all_docs = []
    entity_counts = {}
    
    try:
        document_batches = connector.load_from_state()
        batch_count = 0
        
        for batch in document_batches:
            batch_count += 1
            logger.info(f"Processing batch {batch_count} with {len(batch)} documents")
            
            for doc in batch:
                all_docs.append(doc)
                
                # Count by entity kind
                kind = doc.metadata.get("kind", "unknown")
                entity_counts[kind] = entity_counts.get(kind, 0) + 1
        
        logger.info(f"✓ Successfully fetched {len(all_docs)} documents")
        logger.info("Entity counts by kind:")
        for kind, count in entity_counts.items():
            logger.info(f"  - {kind}: {count}")
        
        return all_docs
    except Exception as e:
        logger.error(f"✗ Entity fetching failed: {e}")
        return []


def test_polling(connector: BackstageConnector) -> bool:
    """Test polling for updates."""
    logger.info("Testing polling functionality...")
    
    try:
        # Use a time window of the last 24 hours
        end_time = datetime.now().timestamp()
        start_time = (datetime.now() - timedelta(days=1)).timestamp()
        
        logger.info(f"Polling for updates between {datetime.fromtimestamp(start_time)} and {datetime.fromtimestamp(end_time)}")
        
        doc_batches = connector.poll_source(start_time, end_time)
        doc_count = sum(len(batch) for batch in doc_batches)
        
        logger.info(f"✓ Successfully polled {doc_count} documents")
        return True
    except Exception as e:
        logger.error(f"✗ Polling failed: {e}")
        return False


def analyze_documents(documents: List[Document]) -> None:
    """Analyze the fetched documents to check for data quality."""
    if not documents:
        logger.warning("No documents to analyze")
        return
    
    logger.info("\nAnalyzing documents for data quality:")
    
    # Sample a few documents for detailed inspection
    sample_size = min(5, len(documents))
    logger.info(f"\nSample of {sample_size} documents:")
    for i, doc in enumerate(documents[:sample_size]):
        logger.info(f"\nDocument {i+1}:")
        logger.info(f"  ID: {doc.id}")
        logger.info(f"  Semantic Identifier: {doc.semantic_identifier}")
        
        # Check if document has text content
        text_length = sum(len(section.text) for section in doc.sections)
        logger.info(f"  Text Length: {text_length} characters")
        
        # Show metadata keys
        logger.info(f"  Metadata Keys: {', '.join(doc.metadata.keys())}")


def main():
    """Run the manual test."""
    logger.info("Starting manual Backstage connector test")
    
    if not check_environment_variables():
        return 1
    
    connector = test_connector_init()
    if not test_authentication(connector):
        return 1

    if not test_validation(connector):
        return 1

    documents = test_fetch_entities(connector)
    if not documents:
        return 1

    analyze_documents(documents)

    if not test_polling(connector):
        return 1
    
    logger.info("\n✓ All tests passed successfully!")
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
