import csv
import shelve

from onyx.connectors.salesforce.shelve_stuff.shelve_utils import (
    get_child_to_parent_shelf_path,
)
from onyx.connectors.salesforce.shelve_stuff.shelve_utils import get_id_type_shelf_path
from onyx.connectors.salesforce.shelve_stuff.shelve_utils import get_object_shelf_path
from onyx.connectors.salesforce.shelve_stuff.shelve_utils import (
    get_parent_to_child_shelf_path,
)
from onyx.connectors.salesforce.utils import SalesforceObject
from onyx.connectors.salesforce.utils import validate_salesforce_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _update_relationship_shelves(
    child_id: str,
    parent_ids: set[str],
) -> None:
    """Update the relationship shelf when a record is updated."""
    try:
        # Convert child_id to string once
        str_child_id = str(child_id)

        # First update child to parent mapping
        with shelve.open(
            get_child_to_parent_shelf_path(),
            flag="c",
            protocol=None,
            writeback=True,
        ) as child_to_parent_db:
            old_parent_ids = set(child_to_parent_db.get(str_child_id, []))
            child_to_parent_db[str_child_id] = list(parent_ids)

            # Calculate differences outside the next context manager
            parent_ids_to_remove = old_parent_ids - parent_ids
            parent_ids_to_add = parent_ids - old_parent_ids

            # Only sync once at the end
            child_to_parent_db.sync()

        # Then update parent to child mapping in a single transaction
        if not parent_ids_to_remove and not parent_ids_to_add:
            return
        with shelve.open(
            get_parent_to_child_shelf_path(),
            flag="c",
            protocol=None,
            writeback=True,
        ) as parent_to_child_db:
            # Process all removals first
            for parent_id in parent_ids_to_remove:
                str_parent_id = str(parent_id)
                existing_children = set(parent_to_child_db.get(str_parent_id, []))
                if str_child_id in existing_children:
                    existing_children.remove(str_child_id)
                    parent_to_child_db[str_parent_id] = list(existing_children)

            # Then process all additions
            for parent_id in parent_ids_to_add:
                str_parent_id = str(parent_id)
                existing_children = set(parent_to_child_db.get(str_parent_id, []))
                existing_children.add(str_child_id)
                parent_to_child_db[str_parent_id] = list(existing_children)

            # Single sync at the end
            parent_to_child_db.sync()

    except Exception as e:
        logger.error(f"Error updating relationship shelves: {e}")
        logger.error(f"Child ID: {child_id}, Parent IDs: {parent_ids}")
        raise


def get_child_ids(parent_id: str) -> set[str]:
    """Get all child IDs for a given parent ID.

    Args:
        parent_id: The ID of the parent object

    Returns:
        A set of child object IDs
    """
    with shelve.open(get_parent_to_child_shelf_path()) as parent_to_child_db:
        return set(parent_to_child_db.get(parent_id, []))


def update_sf_db_with_csv(
    object_type: str,
    csv_download_path: str,
) -> list[str]:
    """Update the SF DB with a CSV file using shelve storage."""
    updated_ids = []
    shelf_path = get_object_shelf_path(object_type)

    # First read the CSV to get all the data
    with open(csv_download_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            id = row["Id"]
            parent_ids = set()
            field_to_remove: set[str] = set()
            # Update relationship shelves for any parent references
            for field, value in row.items():
                if validate_salesforce_id(value) and field != "Id":
                    parent_ids.add(value)
                    field_to_remove.add(field)
                if not value:
                    field_to_remove.add(field)
            _update_relationship_shelves(id, parent_ids)
            for field in field_to_remove:
                # We use this to extract the Primary Owner later
                if field != "LastModifiedById":
                    del row[field]

            # Update the main object shelf
            with shelve.open(shelf_path) as object_type_db:
                object_type_db[id] = row
            # Update the ID-to-type mapping shelf
            with shelve.open(get_id_type_shelf_path()) as id_type_db:
                id_type_db[id] = object_type

            updated_ids.append(id)

    # os.remove(csv_download_path)
    return updated_ids


def get_type_from_id(object_id: str) -> str | None:
    """Get the type of an object from its ID."""
    # Look up the object type from the ID-to-type mapping
    with shelve.open(get_id_type_shelf_path()) as id_type_db:
        if object_id not in id_type_db:
            logger.warning(f"Object ID {object_id} not found in ID-to-type mapping")
            return None
        return id_type_db[object_id]


def get_record(
    object_id: str, object_type: str | None = None
) -> SalesforceObject | None:
    """
    Retrieve the record and return it as a SalesforceObject.
    The object type will be looked up from the ID-to-type mapping shelf.
    """
    if object_type is None:
        if not (object_type := get_type_from_id(object_id)):
            return None

    shelf_path = get_object_shelf_path(object_type)
    with shelve.open(shelf_path) as db:
        if object_id not in db:
            logger.warning(f"Object ID {object_id} not found in {shelf_path}")
            return None
        data = db[object_id]
        return SalesforceObject(
            id=object_id,
            type=object_type,
            data=data,
        )


def find_ids_by_type(object_type: str) -> list[str]:
    """
    Find all object IDs for rows of the specified type.
    """
    shelf_path = get_object_shelf_path(object_type)
    try:
        with shelve.open(shelf_path) as db:
            return list(db.keys())
    except FileNotFoundError:
        return []


def get_affected_parent_ids_by_type(
    updated_ids: set[str], parent_types: list[str]
) -> dict[str, set[str]]:
    """Get IDs of objects that are of the specified parent types and are either in the updated_ids
    or have children in the updated_ids.

    Args:
        updated_ids: List of IDs that were updated
        parent_types: List of object types to filter by

    Returns:
        A dictionary of IDs that match the criteria
    """
    affected_ids_by_type: dict[str, set[str]] = {}

    # Check each updated ID
    for updated_id in updated_ids:
        # Add the ID itself if it's of a parent type
        updated_type = get_type_from_id(updated_id)
        if updated_type in parent_types:
            affected_ids_by_type.setdefault(updated_type, set()).add(updated_id)
            continue

        # Get parents of this ID and add them if they're of a parent type
        with shelve.open(get_child_to_parent_shelf_path()) as child_to_parent_db:
            parent_ids = child_to_parent_db.get(updated_id, [])
            for parent_id in parent_ids:
                parent_type = get_type_from_id(parent_id)
                if parent_type in parent_types:
                    affected_ids_by_type.setdefault(parent_type, set()).add(parent_id)

    return affected_ids_by_type
