#!/usr/bin/env python3
"""
Simple test script for the Coda connector.
Run this with: python3 test_coda_basic.py

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Have at least one Coda doc with some pages
"""
import os
import sys

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.connector import CodaConnector


def test_import():
    """Test that the connector can be imported"""
    print("✓ Import successful")


def test_instantiation():
    """Test that the connector can be instantiated"""
    connector = CodaConnector()
    assert connector is not None
    assert connector.batch_size > 0
    print(f"✓ Connector instantiated: {connector.__class__.__name__}")


def test_credentials():
    """Test credential loading"""
    api_token = os.environ.get("CODA_API_TOKEN")
    if not api_token:
        print("⚠ CODA_API_TOKEN not set, skipping credential test")
        return False

    connector = CodaConnector()
    connector.load_credentials({"coda_api_token": api_token})
    assert "Authorization" in connector.headers
    print("✓ Credentials loaded successfully")
    return True


def test_validation():
    """Test connector validation"""
    api_token = os.environ.get("CODA_API_TOKEN")
    if not api_token:
        print("⚠ CODA_API_TOKEN not set, skipping validation test")
        return

    connector = CodaConnector()
    connector.load_credentials({"coda_api_token": api_token})

    try:
        connector.validate_connector_settings()
        print("✓ Validation passed")
    except Exception as e:
        print(f"✗ Validation failed: {e}")
        raise


def test_registry():
    """Test that connector is registered"""
    from onyx.connectors.factory import identify_connector_class

    cls = identify_connector_class(DocumentSource.CODA)
    assert cls.__name__ == "CodaConnector"
    print(f"✓ Connector registered: {cls.__name__}")


def test_fetch_pages():
    """Test that pages can be fetched from Coda"""
    api_token = os.environ.get("CODA_API_TOKEN")
    if not api_token:
        print("⚠ CODA_API_TOKEN not set, skipping page fetch test")
        return

    connector = CodaConnector()
    connector.load_credentials({"coda_api_token": api_token})

    try:
        # Fetch docs
        docs_response = connector._fetch_docs()
        docs = docs_response.get("items", [])

        if not docs:
            print("⚠ No docs found in Coda workspace")
            return

        print(f"✓ Fetched {len(docs)} doc(s)")

        # Test fetching pages from the first doc
        first_doc = docs[0]
        doc_id = first_doc["id"]
        doc_name = first_doc["name"]

        print(f"  Testing with doc: '{doc_name}' (ID: {doc_id})")

        pages_response = connector._fetch_pages(doc_id)
        pages = pages_response.get("items", [])

        print(f"✓ Fetched {len(pages)} page(s) from doc '{doc_name}'")

        if pages:
            # Show details of first page
            first_page = pages[0]
            print(
                f"  First page: '{first_page.get('name')}' (ID: {first_page.get('id')})"
            )
            print(f"  Content type: {first_page.get('contentType')}")
            print(f"  Updated at: {first_page.get('updatedAt')}")

        # Test content export for first page if available
        if pages:
            page_id = pages[0]["id"]
            page_name = pages[0]["name"]
            print(f"  Attempting to export content for page '{page_name}'...")

            content = connector._export_page_content(doc_id, page_id)
            if content:
                content_preview = content[:100].replace("\n", " ")
                print(
                    f"✓ Exported page content ({len(content)} chars): {content_preview}..."
                )
            else:
                print(
                    "⚠ Page content export returned empty (this may be normal for empty pages)"
                )

    except Exception as e:
        print(f"✗ Page fetch test failed: {e}")
        raise


def test_doc_ids_filtering():
    """Test that doc_ids filtering works"""
    api_token = os.environ.get("CODA_API_TOKEN")
    if not api_token:
        print("⚠ CODA_API_TOKEN not set, skipping doc_ids filtering test")
        return

    # First fetch all docs to get a valid ID
    connector = CodaConnector()
    connector.load_credentials({"coda_api_token": api_token})
    docs_response = connector._fetch_docs()
    docs = docs_response.get("items", [])

    if not docs:
        print("⚠ No docs found in Coda workspace, skipping doc_ids filtering test")
        return

    target_doc = docs[0]
    target_doc_id = target_doc["id"]
    print(f"  Testing filtering with doc: '{target_doc['name']}' (ID: {target_doc_id})")

    # Initialize connector with specific doc_id
    filtered_connector = CodaConnector(doc_ids=[target_doc_id])
    filtered_connector.load_credentials({"coda_api_token": api_token})

    # Test load_from_state
    gen = filtered_connector.load_from_state()

    # We just want to verify that we only process the target doc
    # Since load_from_state yields documents (pages), we can't directly check the docs list
    # But we can check the metadata of the yielded documents

    processed_doc_ids = set()
    try:
        for doc_batch in gen:
            for doc in doc_batch:
                processed_doc_ids.add(doc.metadata.get("doc_id"))
    except Exception as e:
        print(f"✗ Error during filtered load: {e}")
        raise

    if not processed_doc_ids:
        print("⚠ No pages found in target doc")
    else:
        assert len(processed_doc_ids) == 1
        assert target_doc_id in processed_doc_ids
        print("✓ Filtering successful: Only target doc was processed")


if __name__ == "__main__":
    print("Testing Coda Connector Implementation\n")
    print("=" * 60)

    try:
        print("\n1. Basic Tests")
        print("-" * 60)
        test_import()
        test_instantiation()
        has_token = test_credentials()
        test_registry()

        if has_token:
            print("\n2. API Tests")
            print("-" * 60)
            test_validation()

            print("\n3. Page Fetch Tests")
            print("-" * 60)
            test_fetch_pages()

            print("\n4. Doc IDs Filtering Tests")
            print("-" * 60)
            test_doc_ids_filtering()

            print("\n" + "=" * 60)
            print("✅ All tests passed!")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print(
                "⚠ Basic tests passed (API tests skipped - set CODA_API_TOKEN to run)"
            )
            print("=" * 60)
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ Tests failed: {e}")
        print("=" * 60)
        import traceback

        traceback.print_exc()
        sys.exit(1)
