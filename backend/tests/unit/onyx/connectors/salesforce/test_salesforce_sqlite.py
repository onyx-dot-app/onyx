import csv
import json
import os
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import cast

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.connectors.salesforce.doc_conversion import _extract_section
from onyx.connectors.salesforce.doc_conversion import ID_PREFIX
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.connectors.salesforce.salesforce_calls import _bulk_retrieve_from_salesforce
from onyx.connectors.salesforce.salesforce_calls import _make_time_filter_for_sf_type
from onyx.connectors.salesforce.salesforce_calls import _make_time_filtered_query
from onyx.connectors.salesforce.salesforce_calls import get_object_by_id_query
from onyx.connectors.salesforce.sqlite_functions import OnyxSalesforceSQLite
from onyx.connectors.salesforce.utils import ACCOUNT_OBJECT_TYPE
from onyx.connectors.salesforce.utils import MODIFIED_FIELD
from onyx.connectors.salesforce.utils import USER_OBJECT_TYPE
from onyx.utils.logger import setup_logger

# from onyx.connectors.salesforce.onyx_salesforce_type import OnyxSalesforceType
# from onyx.connectors.salesforce.salesforce_calls import get_children_of_sf_type

logger = setup_logger()


_VALID_SALESFORCE_IDS = [
    "001bm00000fd9Z3AAI",
    "001bm00000fdYTdAAM",
    "001bm00000fdYTeAAM",
    "001bm00000fdYTfAAM",
    "001bm00000fdYTgAAM",
    "001bm00000fdYThAAM",
    "001bm00000fdYTiAAM",
    "001bm00000fdYTjAAM",
    "001bm00000fdYTkAAM",
    "001bm00000fdYTlAAM",
    "001bm00000fdYTmAAM",
    "001bm00000fdYTnAAM",
    "001bm00000fdYToAAM",
    "500bm00000XoOxtAAF",
    "500bm00000XoOxuAAF",
    "500bm00000XoOxvAAF",
    "500bm00000XoOxwAAF",
    "500bm00000XoOxxAAF",
    "500bm00000XoOxyAAF",
    "500bm00000XoOxzAAF",
    "500bm00000XoOy0AAF",
    "500bm00000XoOy1AAF",
    "500bm00000XoOy2AAF",
    "500bm00000XoOy3AAF",
    "500bm00000XoOy4AAF",
    "500bm00000XoOy5AAF",
    "500bm00000XoOy6AAF",
    "500bm00000XoOy7AAF",
    "500bm00000XoOy8AAF",
    "500bm00000XoOy9AAF",
    "500bm00000XoOyAAAV",
    "500bm00000XoOyBAAV",
    "500bm00000XoOyCAAV",
    "500bm00000XoOyDAAV",
    "500bm00000XoOyEAAV",
    "500bm00000XoOyFAAV",
    "500bm00000XoOyGAAV",
    "500bm00000XoOyHAAV",
    "500bm00000XoOyIAAV",
    "003bm00000EjHCjAAN",
    "003bm00000EjHCkAAN",
    "003bm00000EjHClAAN",
    "003bm00000EjHCmAAN",
    "003bm00000EjHCnAAN",
    "003bm00000EjHCoAAN",
    "003bm00000EjHCpAAN",
    "003bm00000EjHCqAAN",
    "003bm00000EjHCrAAN",
    "003bm00000EjHCsAAN",
    "003bm00000EjHCtAAN",
    "003bm00000EjHCuAAN",
    "003bm00000EjHCvAAN",
    "003bm00000EjHCwAAN",
    "003bm00000EjHCxAAN",
    "003bm00000EjHCyAAN",
    "003bm00000EjHCzAAN",
    "003bm00000EjHD0AAN",
    "003bm00000EjHD1AAN",
    "003bm00000EjHD2AAN",
    "550bm00000EXc2tAAD",
    "006bm000006kyDpAAI",
    "006bm000006kyDqAAI",
    "006bm000006kyDrAAI",
    "006bm000006kyDsAAI",
    "006bm000006kyDtAAI",
    "006bm000006kyDuAAI",
    "006bm000006kyDvAAI",
    "006bm000006kyDwAAI",
    "006bm000006kyDxAAI",
    "006bm000006kyDyAAI",
    "006bm000006kyDzAAI",
    "006bm000006kyE0AAI",
    "006bm000006kyE1AAI",
    "006bm000006kyE2AAI",
    "006bm000006kyE3AAI",
    "006bm000006kyE4AAI",
    "006bm000006kyE5AAI",
    "006bm000006kyE6AAI",
    "006bm000006kyE7AAI",
    "006bm000006kyE8AAI",
    "006bm000006kyE9AAI",
    "006bm000006kyEAAAY",
    "006bm000006kyEBAAY",
    "006bm000006kyECAAY",
    "006bm000006kyEDAAY",
    "006bm000006kyEEAAY",
    "006bm000006kyEFAAY",
    "006bm000006kyEGAAY",
    "006bm000006kyEHAAY",
    "006bm000006kyEIAAY",
    "006bm000006kyEJAAY",
    "005bm000009zy0TAAQ",
    "005bm000009zy25AAA",
    "005bm000009zy26AAA",
    "005bm000009zy28AAA",
    "005bm000009zy29AAA",
    "005bm000009zy2AAAQ",
    "005bm000009zy2BAAQ",
]


def _clear_sf_db(directory: str) -> None:
    """
    Clears the SF DB by deleting all files in the data directory.
    """
    shutil.rmtree(directory, ignore_errors=True)


def _create_csv_file_and_update_db(
    sf_db: OnyxSalesforceSQLite,
    object_type: str,
    records: list[dict],
    filename: str = "test_data.csv",
) -> None:
    """
    Creates a CSV file for the given object type and records.

    Args:
        object_type: The Salesforce object type (e.g. ACCOUNT_OBJECT_TYPE, "Contact")
        records: List of dictionaries containing the record data
        filename: Name of the CSV file to create (default: test_data.csv)
    """
    if not records:
        return

    # Get all unique fields from records
    fields: set[str] = set()
    for record in records:
        fields.update(record.keys())
    fields = set(sorted(list(fields)))  # Sort for consistent order

    # Create CSV file
    with tempfile.TemporaryDirectory() as directory:
        csv_path = os.path.join(directory, filename)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for record in records:
                writer.writerow(record)

        # Update the database with the CSV
        sf_db.update_from_csv(object_type, csv_path)


def _create_csv_with_example_data(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Creates CSV files with example data, organized by object type.
    """
    example_data: dict[str, list[dict]] = {
        ACCOUNT_OBJECT_TYPE: [
            {
                "Id": _VALID_SALESFORCE_IDS[0],
                "Name": "Acme Inc.",
                "BillingCity": "New York",
                "Industry": "Technology",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[1],
                "Name": "Globex Corp",
                "BillingCity": "Los Angeles",
                "Industry": "Manufacturing",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[2],
                "Name": "Initech",
                "BillingCity": "Austin",
                "Industry": "Software",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[3],
                "Name": "TechCorp Solutions",
                "BillingCity": "San Francisco",
                "Industry": "Software",
                "AnnualRevenue": 5000000,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[4],
                "Name": "BioMed Research",
                "BillingCity": "Boston",
                "Industry": "Healthcare",
                "AnnualRevenue": 12000000,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[5],
                "Name": "Green Energy Co",
                "BillingCity": "Portland",
                "Industry": "Energy",
                "AnnualRevenue": 8000000,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[6],
                "Name": "DataFlow Analytics",
                "BillingCity": "Seattle",
                "Industry": "Technology",
                "AnnualRevenue": 3000000,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[7],
                "Name": "Cloud Nine Services",
                "BillingCity": "Denver",
                "Industry": "Cloud Computing",
                "AnnualRevenue": 7000000,
            },
        ],
        "Contact": [
            {
                "Id": _VALID_SALESFORCE_IDS[40],
                "FirstName": "John",
                "LastName": "Doe",
                "Email": "john.doe@acme.com",
                "Title": "CEO",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[41],
                "FirstName": "Jane",
                "LastName": "Smith",
                "Email": "jane.smith@acme.com",
                "Title": "CTO",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[42],
                "FirstName": "Bob",
                "LastName": "Johnson",
                "Email": "bob.j@globex.com",
                "Title": "Sales Director",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[43],
                "FirstName": "Sarah",
                "LastName": "Chen",
                "Email": "sarah.chen@techcorp.com",
                "Title": "Product Manager",
                "Phone": "415-555-0101",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[44],
                "FirstName": "Michael",
                "LastName": "Rodriguez",
                "Email": "m.rodriguez@biomed.com",
                "Title": "Research Director",
                "Phone": "617-555-0202",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[45],
                "FirstName": "Emily",
                "LastName": "Green",
                "Email": "emily.g@greenenergy.com",
                "Title": "Sustainability Lead",
                "Phone": "503-555-0303",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[46],
                "FirstName": "David",
                "LastName": "Kim",
                "Email": "david.kim@dataflow.com",
                "Title": "Data Scientist",
                "Phone": "206-555-0404",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[47],
                "FirstName": "Rachel",
                "LastName": "Taylor",
                "Email": "r.taylor@cloudnine.com",
                "Title": "Cloud Architect",
                "Phone": "303-555-0505",
            },
        ],
        "Opportunity": [
            {
                "Id": _VALID_SALESFORCE_IDS[62],
                "Name": "Acme Server Upgrade",
                "Amount": 50000,
                "Stage": "Prospecting",
                "CloseDate": "2024-06-30",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[63],
                "Name": "Globex Manufacturing Line",
                "Amount": 150000,
                "Stage": "Negotiation",
                "CloseDate": "2024-03-15",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[64],
                "Name": "Initech Software License",
                "Amount": 75000,
                "Stage": "Closed Won",
                "CloseDate": "2024-01-30",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[65],
                "Name": "TechCorp AI Implementation",
                "Amount": 250000,
                "Stage": "Needs Analysis",
                "CloseDate": "2024-08-15",
                "Probability": 60,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[66],
                "Name": "BioMed Lab Equipment",
                "Amount": 500000,
                "Stage": "Value Proposition",
                "CloseDate": "2024-09-30",
                "Probability": 75,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[67],
                "Name": "Green Energy Solar Project",
                "Amount": 750000,
                "Stage": "Proposal",
                "CloseDate": "2024-07-15",
                "Probability": 80,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[68],
                "Name": "DataFlow Analytics Platform",
                "Amount": 180000,
                "Stage": "Negotiation",
                "CloseDate": "2024-05-30",
                "Probability": 90,
            },
            {
                "Id": _VALID_SALESFORCE_IDS[69],
                "Name": "Cloud Nine Infrastructure",
                "Amount": 300000,
                "Stage": "Qualification",
                "CloseDate": "2024-10-15",
                "Probability": 40,
            },
        ],
    }

    # Create CSV files for each object type
    for object_type, records in example_data.items():
        _create_csv_file_and_update_db(sf_db, object_type, records)


def _test_query(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests querying functionality by verifying:
    1. All expected Account IDs are found
    2. Each Account's data matches what was inserted
    """
    # Expected test data for verification
    expected_accounts: dict[str, dict[str, str | int]] = {
        _VALID_SALESFORCE_IDS[0]: {
            "Name": "Acme Inc.",
            "BillingCity": "New York",
            "Industry": "Technology",
        },
        _VALID_SALESFORCE_IDS[1]: {
            "Name": "Globex Corp",
            "BillingCity": "Los Angeles",
            "Industry": "Manufacturing",
        },
        _VALID_SALESFORCE_IDS[2]: {
            "Name": "Initech",
            "BillingCity": "Austin",
            "Industry": "Software",
        },
        _VALID_SALESFORCE_IDS[3]: {
            "Name": "TechCorp Solutions",
            "BillingCity": "San Francisco",
            "Industry": "Software",
            "AnnualRevenue": 5000000,
        },
        _VALID_SALESFORCE_IDS[4]: {
            "Name": "BioMed Research",
            "BillingCity": "Boston",
            "Industry": "Healthcare",
            "AnnualRevenue": 12000000,
        },
        _VALID_SALESFORCE_IDS[5]: {
            "Name": "Green Energy Co",
            "BillingCity": "Portland",
            "Industry": "Energy",
            "AnnualRevenue": 8000000,
        },
        _VALID_SALESFORCE_IDS[6]: {
            "Name": "DataFlow Analytics",
            "BillingCity": "Seattle",
            "Industry": "Technology",
            "AnnualRevenue": 3000000,
        },
        _VALID_SALESFORCE_IDS[7]: {
            "Name": "Cloud Nine Services",
            "BillingCity": "Denver",
            "Industry": "Cloud Computing",
            "AnnualRevenue": 7000000,
        },
    }

    # Get all Account IDs
    account_ids = sf_db.find_ids_by_type(ACCOUNT_OBJECT_TYPE)

    # Verify we found all expected accounts
    assert len(account_ids) == len(
        expected_accounts
    ), f"Expected {len(expected_accounts)} accounts, found {len(account_ids)}"
    assert set(account_ids) == set(
        expected_accounts.keys()
    ), "Found account IDs don't match expected IDs"

    # Verify each account's data
    for acc_id in account_ids:
        combined = sf_db.get_record(acc_id)
        assert combined is not None, f"Could not find account {acc_id}"

        expected = expected_accounts[acc_id]

        # Verify account data matches
        for key, value in expected.items():
            value = str(value)
            assert (
                combined.data[key] == value
            ), f"Account {acc_id} field {key} expected {value}, got {combined.data[key]}"

    print("All query tests passed successfully!")


def _test_upsert(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests upsert functionality by:
    1. Updating an existing account
    2. Creating a new account
    3. Verifying both operations were successful
    """
    # Create CSV for updating an existing account and adding a new one
    update_data: list[dict[str, str | int]] = [
        {
            "Id": _VALID_SALESFORCE_IDS[0],
            "Name": "Acme Inc. Updated",
            "BillingCity": "New York",
            "Industry": "Technology",
            "Description": "Updated company info",
        },
        {
            "Id": _VALID_SALESFORCE_IDS[2],
            "Name": "New Company Inc.",
            "BillingCity": "Miami",
            "Industry": "Finance",
            "AnnualRevenue": 1000000,
        },
    ]

    _create_csv_file_and_update_db(
        sf_db, ACCOUNT_OBJECT_TYPE, update_data, "update_data.csv"
    )

    # Verify the update worked
    updated_record = sf_db.get_record(_VALID_SALESFORCE_IDS[0])
    assert updated_record is not None, "Updated record not found"
    assert updated_record.data["Name"] == "Acme Inc. Updated", "Name not updated"
    assert (
        updated_record.data["Description"] == "Updated company info"
    ), "Description not added"

    # Verify the new record was created
    new_record = sf_db.get_record(_VALID_SALESFORCE_IDS[2])
    assert new_record is not None, "New record not found"
    assert new_record.data["Name"] == "New Company Inc.", "New record name incorrect"
    assert new_record.data["AnnualRevenue"] == "1000000", "New record revenue incorrect"

    print("All upsert tests passed successfully!")


def _test_relationships(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests relationship shelf updates and queries by:
    1. Creating test data with relationships
    2. Verifying the relationships are correctly stored
    3. Testing relationship queries
    """
    # Create test data for each object type
    test_data: dict[str, list[dict[str, str | int]]] = {
        "Case": [
            {
                "Id": _VALID_SALESFORCE_IDS[13],
                "AccountId": _VALID_SALESFORCE_IDS[0],
                "Subject": "Test Case 1",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[14],
                "AccountId": _VALID_SALESFORCE_IDS[0],
                "Subject": "Test Case 2",
            },
        ],
        "Contact": [
            {
                "Id": _VALID_SALESFORCE_IDS[48],
                "AccountId": _VALID_SALESFORCE_IDS[0],
                "FirstName": "Test",
                "LastName": "Contact",
            }
        ],
        "Opportunity": [
            {
                "Id": _VALID_SALESFORCE_IDS[62],
                "AccountId": _VALID_SALESFORCE_IDS[0],
                "Name": "Test Opportunity",
                "Amount": 100000,
            }
        ],
    }

    # Create and update CSV files for each object type
    for object_type, records in test_data.items():
        _create_csv_file_and_update_db(
            sf_db, object_type, records, "relationship_test.csv"
        )

    # Test relationship queries
    # All these objects should be children of Acme Inc.
    child_ids = sf_db.get_child_ids(_VALID_SALESFORCE_IDS[0])
    assert len(child_ids) == 4, f"Expected 4 child objects, found {len(child_ids)}"
    assert _VALID_SALESFORCE_IDS[13] in child_ids, "Case 1 not found in relationship"
    assert _VALID_SALESFORCE_IDS[14] in child_ids, "Case 2 not found in relationship"
    assert _VALID_SALESFORCE_IDS[48] in child_ids, "Contact not found in relationship"
    assert (
        _VALID_SALESFORCE_IDS[62] in child_ids
    ), "Opportunity not found in relationship"

    # Test querying relationships for a different account (should be empty)
    other_account_children = sf_db.get_child_ids(_VALID_SALESFORCE_IDS[1])
    assert (
        len(other_account_children) == 0
    ), "Expected no children for different account"

    print("All relationship tests passed successfully!")


def _test_account_with_children(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests querying all accounts and retrieving their child objects.
    This test verifies that:
    1. All accounts can be retrieved
    2. Child objects are correctly linked
    3. Child object data is complete and accurate
    """
    # First get all account IDs
    account_ids = sf_db.find_ids_by_type(ACCOUNT_OBJECT_TYPE)
    assert len(account_ids) > 0, "No accounts found"

    # For each account, get its children and verify the data
    for account_id in account_ids:
        account = sf_db.get_record(account_id)
        assert account is not None, f"Could not find account {account_id}"

        # Get all child objects
        child_ids = sf_db.get_child_ids(account_id)

        # For Acme Inc., verify specific relationships
        if account_id == _VALID_SALESFORCE_IDS[0]:  # Acme Inc.
            assert (
                len(child_ids) == 4
            ), f"Expected 4 children for Acme Inc., found {len(child_ids)}"

            # Get all child records
            child_records = []
            for child_id in child_ids:
                child_record = sf_db.get_record(child_id)
                if child_record is not None:
                    child_records.append(child_record)
            # Verify Cases
            cases = [r for r in child_records if r.type == "Case"]
            assert (
                len(cases) == 2
            ), f"Expected 2 cases for Acme Inc., found {len(cases)}"
            case_subjects = {case.data["Subject"] for case in cases}
            assert "Test Case 1" in case_subjects, "Test Case 1 not found"
            assert "Test Case 2" in case_subjects, "Test Case 2 not found"

            # Verify Contacts
            contacts = [r for r in child_records if r.type == "Contact"]
            assert (
                len(contacts) == 1
            ), f"Expected 1 contact for Acme Inc., found {len(contacts)}"
            contact = contacts[0]
            assert contact.data["FirstName"] == "Test", "Contact first name mismatch"
            assert contact.data["LastName"] == "Contact", "Contact last name mismatch"

            # Verify Opportunities
            opportunities = [r for r in child_records if r.type == "Opportunity"]
            assert (
                len(opportunities) == 1
            ), f"Expected 1 opportunity for Acme Inc., found {len(opportunities)}"
            opportunity = opportunities[0]
            assert (
                opportunity.data["Name"] == "Test Opportunity"
            ), "Opportunity name mismatch"
            assert opportunity.data["Amount"] == "100000", "Opportunity amount mismatch"

    print("All account with children tests passed successfully!")


def _test_relationship_updates(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests that relationships are properly updated when a child object's parent reference changes.
    This test verifies:
    1. Initial relationship is created correctly
    2. When parent reference is updated, old relationship is removed
    3. New relationship is created correctly
    """
    # Create initial test data - Contact linked to Acme Inc.
    initial_contact = [
        {
            "Id": _VALID_SALESFORCE_IDS[40],
            "AccountId": _VALID_SALESFORCE_IDS[0],
            "FirstName": "Test",
            "LastName": "Contact",
        }
    ]
    _create_csv_file_and_update_db(
        sf_db, "Contact", initial_contact, "initial_contact.csv"
    )

    # Verify initial relationship
    acme_children = sf_db.get_child_ids(_VALID_SALESFORCE_IDS[0])
    assert (
        _VALID_SALESFORCE_IDS[40] in acme_children
    ), "Initial relationship not created"

    # Update contact to be linked to Globex Corp instead
    updated_contact = [
        {
            "Id": _VALID_SALESFORCE_IDS[40],
            "AccountId": _VALID_SALESFORCE_IDS[1],
            "FirstName": "Test",
            "LastName": "Contact",
        }
    ]
    _create_csv_file_and_update_db(
        sf_db, "Contact", updated_contact, "updated_contact.csv"
    )

    # Verify old relationship is removed
    acme_children = sf_db.get_child_ids(_VALID_SALESFORCE_IDS[0])
    assert (
        _VALID_SALESFORCE_IDS[40] not in acme_children
    ), "Old relationship not removed"

    # Verify new relationship is created
    globex_children = sf_db.get_child_ids(_VALID_SALESFORCE_IDS[1])
    assert _VALID_SALESFORCE_IDS[40] in globex_children, "New relationship not created"

    print("All relationship update tests passed successfully!")


def _test_get_affected_parent_ids(sf_db: OnyxSalesforceSQLite) -> None:
    """
    Tests get_affected_parent_ids functionality by verifying:
    1. IDs that are directly in the parent_types list are included
    2. IDs that have children in the updated_ids list are included
    3. IDs that are neither of the above are not included
    """
    # Create test data with relationships
    test_data = {
        ACCOUNT_OBJECT_TYPE: [
            {
                "Id": _VALID_SALESFORCE_IDS[0],
                "Name": "Parent Account 1",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[1],
                "Name": "Parent Account 2",
            },
            {
                "Id": _VALID_SALESFORCE_IDS[2],
                "Name": "Not Affected Account",
            },
        ],
        "Contact": [
            {
                "Id": _VALID_SALESFORCE_IDS[40],
                "AccountId": _VALID_SALESFORCE_IDS[0],
                "FirstName": "Child",
                "LastName": "Contact",
            }
        ],
    }

    # Create and update CSV files for test data
    for object_type, records in test_data.items():
        _create_csv_file_and_update_db(sf_db, object_type, records)

    # Test Case 1: Account directly in updated_ids and parent_types
    updated_ids = [_VALID_SALESFORCE_IDS[1]]  # Parent Account 2
    parent_types = set([ACCOUNT_OBJECT_TYPE])
    affected_ids_by_type = defaultdict(set)
    for parent_type, parent_id, _ in sf_db.get_changed_parent_ids_by_type(
        updated_ids, parent_types
    ):
        affected_ids_by_type[parent_type].add(parent_id)
    assert (
        ACCOUNT_OBJECT_TYPE in affected_ids_by_type
    ), "Account type not in affected_ids_by_type"
    assert (
        _VALID_SALESFORCE_IDS[1] in affected_ids_by_type[ACCOUNT_OBJECT_TYPE]
    ), "Direct parent ID not included"

    # Test Case 2: Account with child in updated_ids
    updated_ids = [_VALID_SALESFORCE_IDS[40]]  # Child Contact
    parent_types = set([ACCOUNT_OBJECT_TYPE])
    affected_ids_by_type = defaultdict(set)
    for parent_type, parent_id, _ in sf_db.get_changed_parent_ids_by_type(
        updated_ids, parent_types
    ):
        affected_ids_by_type[parent_type].add(parent_id)
    assert (
        ACCOUNT_OBJECT_TYPE in affected_ids_by_type
    ), "Account type not in affected_ids_by_type"
    assert (
        _VALID_SALESFORCE_IDS[0] in affected_ids_by_type[ACCOUNT_OBJECT_TYPE]
    ), "Parent of updated child not included"

    # Test Case 3: Both direct and indirect affects
    updated_ids = [_VALID_SALESFORCE_IDS[1], _VALID_SALESFORCE_IDS[40]]  # Both cases
    parent_types = set([ACCOUNT_OBJECT_TYPE])
    affected_ids_by_type = defaultdict(set)
    for parent_type, parent_id, _ in sf_db.get_changed_parent_ids_by_type(
        updated_ids, parent_types
    ):
        affected_ids_by_type[parent_type].add(parent_id)
    assert (
        ACCOUNT_OBJECT_TYPE in affected_ids_by_type
    ), "Account type not in affected_ids_by_type"
    affected_ids = affected_ids_by_type[ACCOUNT_OBJECT_TYPE]
    assert len(affected_ids) == 2, "Expected exactly two affected parent IDs"
    assert _VALID_SALESFORCE_IDS[0] in affected_ids, "Parent of child not included"
    assert _VALID_SALESFORCE_IDS[1] in affected_ids, "Direct parent ID not included"
    assert (
        _VALID_SALESFORCE_IDS[2] not in affected_ids
    ), "Unaffected ID incorrectly included"

    # Test Case 4: No matches
    updated_ids = [_VALID_SALESFORCE_IDS[40]]  # Child Contact
    parent_types = set(["Opportunity"])  # Wrong type
    affected_ids_by_type = defaultdict(set)
    for parent_type, parent_id, _ in sf_db.get_changed_parent_ids_by_type(
        updated_ids, parent_types
    ):
        affected_ids_by_type[parent_type].add(parent_id)
    assert len(affected_ids_by_type) == 0, "Should return empty dict when no matches"

    print("All get_affected_parent_ids tests passed successfully!")


def test_salesforce_sqlite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        _clear_sf_db(directory)

        filename = os.path.join(directory, "salesforce_db.sqlite")
        sf_db = OnyxSalesforceSQLite(filename)
        sf_db.connect()
        sf_db.apply_schema()

        _create_csv_with_example_data(sf_db)

        _test_query(sf_db)

        _test_upsert(sf_db)

        _test_relationships(sf_db)

        _test_account_with_children(sf_db)

        _test_relationship_updates(sf_db)

        _test_get_affected_parent_ids(sf_db)

        sf_db.close()

        _clear_sf_db(directory)


@pytest.mark.skip(reason="Enable when credentials are available")
def test_salesforce_bulk_retrieve() -> None:

    username = os.environ["SF_USERNAME"]
    password = os.environ["SF_PASSWORD"]
    security_token = os.environ["SF_SECURITY_TOKEN"]

    sf_client = OnyxSalesforce(
        username=username,
        password=password,
        security_token=security_token,
        domain=None,
    )

    # onyx_sf_type = OnyxSalesforceType("Contact", sf_client)
    sf_object_name = "Contact"
    queryable_fields = sf_client.get_queryable_fields_by_type(sf_object_name)

    intermediate_time = datetime(2024, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    time_filter = _make_time_filter_for_sf_type(
        queryable_fields, 0, intermediate_time.timestamp()
    )
    assert time_filter

    query = _make_time_filtered_query(queryable_fields, sf_object_name, time_filter)

    with tempfile.TemporaryDirectory() as temp_dir:
        object_type, csv_paths = _bulk_retrieve_from_salesforce(
            sf_object_name, query, temp_dir, sf_client
        )

        assert csv_paths

        # Count rows in the downloaded CSV(s)
        total_data_rows = 0
        csv_files_found = []
        for filename in os.listdir(temp_dir):
            # Ensure we only process files ending with .csv and belonging to the correct object type
            # The filename format is expected to be "ObjectType.some_random_id.csv"
            if filename.endswith(".csv") and filename.startswith(f"{object_type}."):
                filepath = os.path.join(temp_dir, filename)
                csv_files_found.append(filepath)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        try:
                            next(reader)  # Attempt to skip header
                            # Count data rows
                            num_data_rows = sum(1 for _ in reader)
                            logger.info(
                                f"Counted {num_data_rows} data rows in {filename}"
                            )
                            total_data_rows += num_data_rows
                        except StopIteration:
                            # Handle empty file or file with only header
                            logger.info(
                                f"File {filename} is empty or contains only a header."
                            )
                except Exception as e:
                    logger.error(f"Error reading or counting rows in {filename}: {e}")

        logger.info(
            f"Found {len(csv_files_found)} CSV files for {object_type} in {temp_dir}."
        )
        logger.info(
            f"Total data rows across all CSVs for {object_type}: {total_data_rows}"
        )

        assert total_data_rows > 1100 and total_data_rows < 1200


# def test_salesforce_client_sobjects():

#     username = os.environ["SF_USERNAME"]
#     password = os.environ["SF_PASSWORD"]
#     security_token = os.environ["SF_SECURITY_TOKEN"]

#     sf_client = Salesforce(
#         username=username,
#         password=password,
#         security_token=security_token,
#         domain=None,
#     )

#     # does exist
#     record = sf_client.restful("sobjects/005bm000002bBHtAAM")

#     # does exist
#     record = sf_client.sobjects.get("005bm000002bBHtAAM")

#     # doesn't exist
#     record = sf_client.sobjects.get("01234567890ABCDEFG")


def test_normalize_record() -> None:
    """Test normalize record"""

    expected_str = (
        '{"Id": "001bm00000eu6n5AAA", '
        '"LastModifiedDate": "2024-12-24T18:18:29.000Z", '
        '"BillingStreet": "123 Nowhere Parkway", '
        '"CreatedDate": "2024-12-24T18:18:29.000Z", '
        '"IsDeleted": "false", '
        '"SystemModstamp": "2024-12-24T18:18:29.000Z", '
        '"Name": "Some Company", '
        '"LastModifiedById": "005bm000002bBHtAAM", '
        '"PhotoUrl": "/services/images/photo/001bm00000eu6n5AAA", '
        '"BillingCity": "Some Town", '
        '"CleanStatus": "Pending"}'
    )
    current_dir = Path(__file__).parent
    with open(current_dir / "test_account.csv", "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            assert len(row) == 64

            normalized_record, parent_ids = OnyxSalesforceSQLite.normalize_record(row)
            normalized_record_json_str = json.dumps(normalized_record)
            assert normalized_record_json_str == expected_str
            assert "005bm000002bBHtAAM" in parent_ids
            assert len(parent_ids) == 1


def _get_child_records_by_id_query(
    object_id: str,
    sf_type: str,
    child_relationships: list[str],
    relationships_to_fields: dict[str, set[str]],
) -> str:
    """Returns a SOQL query given the object id, type and child relationships.

    When the query is executed, it comes back as result.records[0][child_relationship(s)]
    """

    SUBQUERY_LIMIT = 10

    query = "SELECT "
    for child_relationship in child_relationships:
        # TODO(rkuo): what happens if there is a very large list of child records?
        # is that possible problem?

        # NOTE: we actually have to list out the subqueries we want.
        # We can't use the following shortcuts:
        #   FIELDS(ALL) can include binary fields, so don't use that
        #   FIELDS(CUSTOM) can include aggregate queries, so don't use that
        fields = relationships_to_fields[child_relationship]
        fields_fragment = ",".join(fields)
        query += f"(SELECT {fields_fragment} FROM {child_relationship} LIMIT {SUBQUERY_LIMIT}), "

    query = query.rstrip(", ")
    query += f" FROM {sf_type} WHERE Id = '{object_id}'"
    return query


# TODO: move these to daily connector tests
@pytest.mark.skip(reason="Enable when credentials are available")
def test_salesforce_connector_single() -> None:
    """Test various manipulations of a single record"""

    # this record has some opportunity child records
    parent_id = "001bm00000BXfhEAAT"
    parent_type = ACCOUNT_OBJECT_TYPE
    parent_types = [parent_type]

    username = os.environ["SF_USERNAME"]
    password = os.environ["SF_PASSWORD"]
    security_token = os.environ["SF_SECURITY_TOKEN"]

    sf_client = OnyxSalesforce(
        username=username,
        password=password,
        security_token=security_token,
        domain=None,
    )

    # onyx_parent_sf_type = OnyxSalesforceType(parent_type, sf_client)

    child_types: set[str] = set()
    parent_to_child_types: dict[str, set[str]] = {}  # map from parent to child types
    parent_to_child_relationships: dict[str, set[str]] = (
        {}
    )  # map from parent to child relationships
    child_to_parent_types: dict[str, set[str]] = (
        {}
    )  # reverse map from child to parent types
    child_relationship_to_queryable_fields: dict[str, set[str]] = {}

    # parent_reference_fields_by_type: dict[str, dict[str, list[str]]] = {}

    # Step 1 - make a list of all the types to download (parent + direct child + USER_OBJECT_TYPE)
    logger.info(f"Parent object types: num={len(parent_types)} list={parent_types}")
    for parent_type_working in parent_types:
        child_types_working = sf_client.get_children_of_sf_type(parent_type_working)
        logger.debug(f"Found {len(child_types)} child types for {parent_type_working}")

        for child_type, child_relationship in child_types_working.items():
            # onyx_sf_type = OnyxSalesforceType(child_type, sf_client)

            # map parent to child type
            if parent_type_working not in parent_to_child_types:
                parent_to_child_types[parent_type_working] = set()
            parent_to_child_types[parent_type_working].add(child_type)

            # map parent to child relationship
            if parent_type_working not in parent_to_child_relationships:
                parent_to_child_relationships[parent_type_working] = set()
            parent_to_child_relationships[parent_type_working].add(child_relationship)

            # reverse map child to parent
            if child_relationship not in child_to_parent_types:
                child_to_parent_types[child_type] = set()
            child_to_parent_types[child_type].add(parent_type_working)

            child_relationship_to_queryable_fields[child_relationship] = (
                sf_client.get_queryable_fields_by_type(child_type)
            )

        child_types.update(list(child_types_working.keys()))
        logger.info(
            f"Child object types: parent={parent_type_working} num={len(child_types_working)} list={child_types_working.keys()}"
        )

    # queryable_fields_attachment = _get_all_queryable_fields_of_sf_type(sf_client, "Attachment")
    # queryable_fields_contact_point_email = _get_all_queryable_fields_of_sf_type(sf_client, "ContactPointEmail")

    # queryable_str = ",".join(queryable_fields_contact_point_email)
    sections: list[TextSection] = []

    queryable_fields = sf_client.get_queryable_fields_by_type(parent_type)
    query = get_object_by_id_query(parent_id, parent_type, queryable_fields)
    result = sf_client.query(query)
    records = result["records"]
    record = records[0]
    assert record["attributes"]["type"] == ACCOUNT_OBJECT_TYPE
    parent_last_modified_date = record.get(MODIFIED_FIELD, "")
    parent_semantic_identifier = record.get("Name", "Unknown Object")
    parent_last_modified_by_id = record.get("LastModifiedById")

    normalized_record, _ = OnyxSalesforceSQLite.normalize_record(record)
    parent_text_section = _extract_section(
        normalized_record, f"https://{sf_client.sf_instance}/{parent_id}"
    )
    sections.append(parent_text_section)

    time_start = time.monotonic()

    # hardcoded testing with just one parent id
    MAX_CHILD_TYPES_IN_QUERY = 20
    child_relationships: list[str] = list(parent_to_child_relationships[parent_type])

    # relationship_status - the child object types added to this dict have been queried
    relationship_status: dict[str, bool] = {}

    child_relationships_batch = []
    for child_relationship in child_relationships:

        # this is binary content, skip it
        if child_relationship == "Attachments":
            continue

        child_relationships_batch.append(child_relationship)
        if len(child_relationships_batch) < MAX_CHILD_TYPES_IN_QUERY:
            continue

        query = _get_child_records_by_id_query(
            parent_id,
            parent_type,
            child_relationships_batch,
            child_relationship_to_queryable_fields,
        )
        print(f"{query=}")

        # sf_type = parent_type
        # query = (
        #     f"SELECT "
        #     f"Id, "
        #     f"(SELECT OwnerId,CreatedDate,Id,Name,BestTimeToContactStartTime,ActiveToDate,"
        #     f"EmailLatestBounceReasonText,CreatedById,LastModifiedDate,LastModifiedById,"
        #     f"PreferenceRank,EmailDomain,BestTimeToContactEndTime,SystemModstamp,EmailMailBox,"
        #     f"LastReferencedDate,UsageType,ActiveFromDate,ParentId,LastViewedDate,IsPrimary,"
        #     f"EmailAddress,EmailLatestBounceDateTime,IsDeleted,BestTimeToContactTimezone "
        #     f"FROM ContactPointEmails LIMIT 10) "
        #     f"FROM {sf_type} WHERE Id = '{parent_id}'"
        # )

        # NOTE: Querying STANDARD and CUSTOM when there are no custom fields results in an
        # non-descriptive error (only root aggregation)
        # sf_type = parent_type
        # query = (
        #     f"SELECT "
        #     f"Id, "
        #     f"(SELECT FIELDS(STANDARD) FROM ContactPointEmails LIMIT 10) "
        #     f"FROM {sf_type} WHERE Id = '{parent_id}'"
        # )

        # query = (
        #     f"SELECT "
        #     f"{sf_type}.Id "
        #     f"FROM {sf_type} WHERE Id = '{parent_id}'"
        # )

        try:
            result = sf_client.query(query)
            print(f"{result=}")
        except Exception:
            logger.exception(f"Query failed: {query=}")
            for child_relationship in child_relationships_batch:
                relationship_status[child_relationship] = False
        else:
            for child_record_key, child_record in result["records"][0].items():
                if child_record_key == "attributes":
                    continue

                if child_record:
                    child_text_section = _extract_section(
                        child_record,
                        f"https://{sf_client.sf_instance}/{child_record_key}",
                    )
                    sections.append(child_text_section)
                    relationship_status[child_record_key] = False
                else:
                    relationship_status[child_record_key] = False
        finally:
            child_relationships_batch.clear()

    if len(child_relationships_batch) > 0:
        query = _get_child_records_by_id_query(
            parent_id,
            parent_types[0],
            child_relationships_batch,
            child_relationship_to_queryable_fields,
        )
        print(f"{query=}")

        try:
            result = sf_client.query(query)
            print(f"{result=}")
        except Exception:
            logger.exception(f"Query failed: {query=}")
            for child_relationship in child_relationships_batch:
                relationship_status[child_relationship] = False
        else:
            for child_record_key, child_record in result["records"][0].items():
                if child_record_key == "attributes":
                    continue

                if child_record:
                    child_text_section = _extract_section(
                        child_record,
                        f"https://{sf_client.sf_instance}/{child_record_key}",
                    )
                    sections.append(child_text_section)
                    relationship_status[child_record_key] = False
                else:
                    relationship_status[child_record_key] = False
        finally:
            child_relationships_batch.clear()

    # get user relationship if present
    primary_owner_list = None
    if parent_last_modified_by_id:
        queryable_user_fields = sf_client.get_queryable_fields_by_type(USER_OBJECT_TYPE)
        query = get_object_by_id_query(
            parent_last_modified_by_id, USER_OBJECT_TYPE, queryable_user_fields
        )
        result = sf_client.query(query)
        user_record = result["records"][0]
        expert_info = BasicExpertInfo(
            first_name=user_record.get("FirstName"),
            last_name=user_record.get("LastName"),
            email=user_record.get("Email"),
            display_name=user_record.get("Name"),
        )

        if (
            expert_info.first_name
            or expert_info.last_name
            or expert_info.email
            or expert_info.display_name
        ):
            primary_owner_list = [expert_info]

    doc = Document(
        id=ID_PREFIX + parent_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.SALESFORCE,
        semantic_identifier=parent_semantic_identifier,
        doc_updated_at=time_str_to_utc(parent_last_modified_date),
        primary_owners=primary_owner_list,
        metadata={},
    )

    assert doc is not None

    time_elapsed = time.monotonic() - time_start
    print(f"elapsed={time_elapsed:.2f}")

    print(f"{relationship_status=}")
