#!/usr/bin/env python3
"""
Test script for the new custom query configuration functionality in SalesforceConnector.

This demonstrates how to use the new custom_query_config parameter to specify
exactly which fields and associations (child objects) to retrieve for each object type.
"""

import json
from typing import Any

from onyx.connectors.salesforce.connector import _validate_custom_query_config
from onyx.connectors.salesforce.connector import SalesforceConnector
from onyx.connectors.salesforce.utils import ACCOUNT_OBJECT_TYPE
from onyx.connectors.salesforce.utils import MODIFIED_FIELD


def test_custom_query_config() -> None:
    """Test the custom query configuration functionality."""

    # Example custom query configuration
    # This specifies exactly which fields and associations to retrieve
    custom_config = {
        ACCOUNT_OBJECT_TYPE: {
            "fields": ["Id", "Name", "Industry", "CreatedDate", MODIFIED_FIELD],
            "associations": {
                "Contact": ["Id", "FirstName", "LastName", "Email"],
                "Opportunity": ["Id", "Name", "StageName", "Amount", "CloseDate"],
            },
        },
        "Lead": {
            "fields": ["Id", "FirstName", "LastName", "Company", "Status"],
            "associations": {},  # No associations for Lead
        },
    }

    # Create connector with custom configuration
    connector = SalesforceConnector(
        batch_size=50, custom_query_config=json.dumps(custom_config)
    )

    print("✅ SalesforceConnector created successfully with custom query config")
    print(f"Parent object list: {connector.parent_object_list}")
    print(f"Custom config keys: {list(custom_config.keys())}")

    # Test that the parent object list is derived from the custom config
    assert connector.parent_object_list == [ACCOUNT_OBJECT_TYPE, "Lead"]
    assert connector.custom_query_config == custom_config

    print("✅ Basic validation passed")


def test_traditional_config() -> None:
    """Test that the traditional requested_objects approach still works."""

    # Traditional approach
    connector = SalesforceConnector(
        batch_size=50, requested_objects=[ACCOUNT_OBJECT_TYPE, "Contact"]
    )

    print("✅ SalesforceConnector created successfully with traditional config")
    print(f"Parent object list: {connector.parent_object_list}")

    # Test that it still works the old way
    assert connector.parent_object_list == [ACCOUNT_OBJECT_TYPE, "Contact"]
    assert connector.custom_query_config is None

    print("✅ Traditional config validation passed")


def test_validation() -> None:
    """Test that invalid configurations are rejected."""

    # Test invalid config structure
    invalid_configs: list[Any] = [
        # Invalid fields type
        {ACCOUNT_OBJECT_TYPE: {"fields": "invalid"}},
        # Invalid associations type
        {ACCOUNT_OBJECT_TYPE: {"associations": "invalid"}},
        # Nested invalid structure
        {ACCOUNT_OBJECT_TYPE: {"associations": {"Contact": {"fields": "invalid"}}}},
    ]

    for i, invalid_config in enumerate(invalid_configs):
        try:
            _validate_custom_query_config(invalid_config)
            assert False, f"Should have raised ValueError for invalid_config[{i}]"
        except ValueError:
            print(f"✅ Correctly rejected invalid config {i}")


if __name__ == "__main__":
    print("Testing SalesforceConnector custom query configuration...")
    print("=" * 60)

    test_custom_query_config()
    print()

    test_traditional_config()
    print()

    test_validation()
    print()

    print("=" * 60)
    print("🎉 All tests passed! The custom query configuration is working correctly.")
    print()
    print("Example usage:")
    print(
        """
# Custom configuration approach
custom_config = {
    ACCOUNT_OBJECT_TYPE: {
        "fields": ["Id", "Name", "Industry"],
        "associations": {
            "Contact": {
                "fields": ["Id", "FirstName", "LastName", "Email"],
                "associations": {}
            }
        }
    }
}

connector = SalesforceConnector(custom_query_config=custom_config)

# Traditional approach (still works)
connector = SalesforceConnector(requested_objects=[ACCOUNT_OBJECT_TYPE, "Contact"])
"""
    )
