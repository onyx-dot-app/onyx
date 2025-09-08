import os
from dataclasses import dataclass
from typing import Any

NAME_FIELD = "Name"
MODIFIED_FIELD = "LastModifiedDate"
ID_FIELD = "Id"
ACCOUNT_OBJECT_TYPE = "Account"
USER_OBJECT_TYPE = "User"


@dataclass
class SalesforceObject:
    id: str
    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ID": self.id,
            "Type": self.type,
            "Data": self.data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SalesforceObject":
        return cls(
            id=data[ID_FIELD],
            type=data["Type"],
            data=data,
        )


# This defines the base path for all data files relative to this file
# AKA BE CAREFUL WHEN MOVING THIS FILE
BASE_DATA_PATH = os.path.join(os.path.dirname(__file__), "data")


def get_sqlite_db_path(directory: str) -> str:
    """Get the path to the sqlite db file."""
    return os.path.join(directory, "salesforce_db.sqlite")


def get_object_type_path(object_type: str) -> str:
    """Get the directory path for a specific object type."""
    type_dir = os.path.join(BASE_DATA_PATH, object_type)
    os.makedirs(type_dir, exist_ok=True)
    return type_dir


_CHECKSUM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
_LOOKUP = {format(i, "05b"): _CHECKSUM_CHARS[i] for i in range(32)}


def validate_salesforce_id(salesforce_id: str) -> bool:
    """Validate the checksum portion of an 18-character Salesforce ID.

    Args:
        salesforce_id: An 18-character Salesforce ID

    Returns:
        bool: True if the checksum is valid, False otherwise
    """
    if len(salesforce_id) != 18:
        return False

    chunks = [salesforce_id[0:5], salesforce_id[5:10], salesforce_id[10:15]]

    checksum = salesforce_id[15:18]
    calculated_checksum = ""

    for chunk in chunks:
        result_string = "".join(
            "1" if char.isupper() else "0" for char in reversed(chunk)
        )
        calculated_checksum += _LOOKUP[result_string]

    return checksum == calculated_checksum
