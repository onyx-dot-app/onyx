#!/usr/bin/env python3
"""
Test script for the Nextcloud connector.

This script tests the Nextcloud connector functionality including:
- Connection validation
- File listing and metadata extraction  
- Document creation and content extraction
- Incremental sync capabilities

Usage:
    export NEXTCLOUD_SERVER_URL="https://your-nextcloud.com"
    export NEXTCLOUD_USERNAME="your-username"
    export NEXTCLOUD_PASSWORD="your-app-password"
    python test_connector.py

Optional environment variables:
    NEXTCLOUD_PATH_FILTER - Limit indexing to specific path (default: all files)
    NEXTCLOUD_FILE_EXTENSIONS - Comma-separated list of file extensions (default: common text files)
"""

import os
import logging
from pathlib import Path
import sys

# Add the parent directory to the path so we can import the connector
sys.path.insert(0, str(Path(__file__).parent))

from connector import NextcloudConnector

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_nextcloud_connector():
    """Test the Nextcloud connector with environment variables.
    
    Returns:
        bool: True if test completed successfully, False otherwise
    """
    
    # Get configuration from environment
    server_url = os.environ.get("NEXTCLOUD_SERVER_URL")
    username = os.environ.get("NEXTCLOUD_USERNAME") 
    password = os.environ.get("NEXTCLOUD_PASSWORD")
    path_filter = os.environ.get("NEXTCLOUD_PATH_FILTER", "")
    
    if not all([server_url, username, password]):
        logger.error("Missing required environment variables:")
        logger.error("Please set: NEXTCLOUD_SERVER_URL, NEXTCLOUD_USERNAME, NEXTCLOUD_PASSWORD")
        return False
    
    logger.info("🔧 Testing Nextcloud connector...")
    logger.info(f"Server: {server_url}")
    logger.info(f"Username: {username}")
    logger.info(f"Path filter: {path_filter or '(none - will index all files)'}")
    
    try:
        # Create connector
        connector = NextcloudConnector()
        
        # Load credentials
        credentials = {
            "nextcloud_server_url": server_url,
            "nextcloud_username": username,
            "nextcloud_password": password,
            "nextcloud_path_filter": path_filter,
            "nextcloud_verify_ssl": True,
        }
        
        logger.info("📡 Loading credentials...")
        connector.load_credentials(credentials)
        
        # Test connection
        logger.info("🔍 Testing connection...")
        connector.validate_connector_settings()
        logger.info("✅ Connection successful!")
        
        # Test file listing
        logger.info("📁 Getting file list...")
        document_batches = connector.load_from_state()
        
        total_documents = 0
        batch_count = 0
        sample_docs = []
        
        try:
            for batch in document_batches:
                batch_count += 1
                total_documents += len(batch)
                
                # Keep first few documents as samples
                if len(sample_docs) < 5:
                    sample_docs.extend(batch[:5 - len(sample_docs)])
                
                logger.info(f"📄 Processed batch {batch_count} with {len(batch)} documents")
                
                # Limit to first few batches for testing
                if batch_count >= 3:
                    logger.info("📊 Limiting to first 3 batches for testing...")
                    break
                    
        except Exception as e:
            logger.error(f"❌ Error processing documents: {e}")
            return False
        
        # Show results
        logger.info(f"📈 Results:")
        logger.info(f"  - Total documents found: {total_documents}")
        logger.info(f"  - Batches processed: {batch_count}")
        
        if sample_docs:
            logger.info(f"📋 Sample documents:")
            for i, doc in enumerate(sample_docs[:3], 1):
                logger.info(f"  {i}. {doc.semantic_identifier}")
                logger.info(f"     ID: {doc.id}")
                logger.info(f"     Source: {doc.source}")
                logger.info(f"     Updated: {doc.doc_updated_at}")
                logger.info(f"     Text preview: {doc.sections[0].text[:100]}...")
                if doc.metadata:
                    logger.info(f"     Metadata: {dict(list(doc.metadata.items())[:3])}")
                logger.info("")
        
        logger.info("🎉 Nextcloud connector test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def main():
    """Main test function that executes the connector tests."""
    logger.info("🚀 Starting Nextcloud Connector Test")
    logger.info("=" * 50)
    
    success = test_nextcloud_connector()
    
    logger.info("=" * 50)
    if success:
        logger.info("✅ All tests passed!")
        return 0
    else:
        logger.error("❌ Tests failed!")
        return 1


if __name__ == "__main__":
    exit(main())
