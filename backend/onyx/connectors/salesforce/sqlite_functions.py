import csv
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from onyx.connectors.salesforce.utils import get_sqlite_db_path
from onyx.connectors.salesforce.utils import SalesforceObject
from onyx.connectors.salesforce.utils import validate_salesforce_id
from onyx.utils.logger import setup_logger
from shared_configs.utils import batch_list

logger = setup_logger()


@contextmanager
def get_db_connection(
    isolation_level: str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Get a database connection with proper isolation level and error handling.

    Args:
        isolation_level: SQLite isolation level. None = default "DEFERRED",
            can be "IMMEDIATE" or "EXCLUSIVE" for more strict isolation.
    """
    # 60 second timeout for locks
    conn = sqlite3.connect(get_sqlite_db_path(), timeout=60.0)

    if isolation_level is not None:
        conn.isolation_level = isolation_level
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the SQLite database with required tables if they don't exist."""
    # Create database directory if it doesn't exist
    os.makedirs(os.path.dirname(get_sqlite_db_path()), exist_ok=True)

    with get_db_connection("EXCLUSIVE") as conn:
        cursor = conn.cursor()

        db_exists = os.path.exists(get_sqlite_db_path())

        if not db_exists:
            # Enable WAL mode for better concurrent access and write performance
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-2000000")  # Use 2GB memory for cache

        # Main table for storing Salesforce objects
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS salesforce_objects (
                id TEXT PRIMARY KEY,
                object_type TEXT NOT NULL,
                data TEXT NOT NULL,  -- JSON serialized data
                last_modified INTEGER DEFAULT (strftime('%s', 'now'))  -- Add timestamp for better cache management
            ) WITHOUT ROWID  -- Optimize for primary key lookups
        """
        )

        # Table for parent-child relationships with covering index
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                child_id TEXT NOT NULL,
                parent_id TEXT NOT NULL,
                PRIMARY KEY (child_id, parent_id)
            ) WITHOUT ROWID  -- Optimize for primary key lookups
        """
        )

        # New table for caching parent-child relationships with object types
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relationship_types (
                child_id TEXT NOT NULL,
                parent_id TEXT NOT NULL,
                parent_type TEXT NOT NULL,
                PRIMARY KEY (child_id, parent_id, parent_type)
            ) WITHOUT ROWID
        """
        )

        # Create a table for User email to ID mapping if it doesn't exist
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_email_map (
                email TEXT PRIMARY KEY,
                user_id TEXT,  -- Nullable to allow for users without IDs
                FOREIGN KEY (user_id) REFERENCES salesforce_objects(id)
            ) WITHOUT ROWID
        """
        )

        # Create indexes if they don't exist (SQLite ignores IF NOT EXISTS for indexes)
        def create_index_if_not_exists(index_name: str, create_statement: str) -> None:
            cursor.execute(
                f"SELECT name FROM sqlite_master WHERE type='index' AND name='{index_name}'"
            )
            if not cursor.fetchone():
                cursor.execute(create_statement)

        create_index_if_not_exists(
            "idx_object_type",
            """
            CREATE INDEX idx_object_type
            ON salesforce_objects(object_type, id)
            WHERE object_type IS NOT NULL
            """,
        )

        create_index_if_not_exists(
            "idx_parent_id",
            """
            CREATE INDEX idx_parent_id
            ON relationships(parent_id, child_id)
            """,
        )

        create_index_if_not_exists(
            "idx_child_parent",
            """
            CREATE INDEX idx_child_parent
            ON relationships(child_id)
            WHERE child_id IS NOT NULL
            """,
        )

        create_index_if_not_exists(
            "idx_relationship_types_lookup",
            """
            CREATE INDEX idx_relationship_types_lookup
            ON relationship_types(parent_type, child_id, parent_id)
            """,
        )

        # Analyze tables to help query planner
        cursor.execute("ANALYZE relationships")
        cursor.execute("ANALYZE salesforce_objects")
        cursor.execute("ANALYZE relationship_types")
        cursor.execute("ANALYZE user_email_map")

        # If database already existed but user_email_map needs to be populated
        cursor.execute("SELECT COUNT(*) FROM user_email_map")
        if cursor.fetchone()[0] == 0:
            _update_user_email_map(conn)

        conn.commit()


def _update_relationship_tables(
    conn: sqlite3.Connection, child_id: str, parent_ids: set[str]
) -> None:
    """Update the relationship tables when a record is updated.

    Args:
        conn: The database connection to use (must be in a transaction)
        child_id: The ID of the child record
        parent_ids: Set of parent IDs to link to
    """
    try:
        cursor = conn.cursor()

        # Get existing parent IDs
        cursor.execute(
            "SELECT parent_id FROM relationships WHERE child_id = ?", (child_id,)
        )
        old_parent_ids = {row[0] for row in cursor.fetchall()}

        # Calculate differences
        parent_ids_to_remove = old_parent_ids - parent_ids
        parent_ids_to_add = parent_ids - old_parent_ids

        # Remove old relationships
        if parent_ids_to_remove:
            cursor.executemany(
                "DELETE FROM relationships WHERE child_id = ? AND parent_id = ?",
                [(child_id, pid) for pid in parent_ids_to_remove],
            )
            # Also remove from relationship_types
            cursor.executemany(
                "DELETE FROM relationship_types WHERE child_id = ? AND parent_id = ?",
                [(child_id, pid) for pid in parent_ids_to_remove],
            )

        # Add new relationships
        if parent_ids_to_add:
            # First add to relationships table
            cursor.executemany(
                "INSERT INTO relationships (child_id, parent_id) VALUES (?, ?)",
                [(child_id, pid) for pid in parent_ids_to_add],
            )

            # Then get the types of the parent objects and add to relationship_types
            for parent_id in parent_ids_to_add:
                cursor.execute(
                    "SELECT object_type FROM salesforce_objects WHERE id = ?",
                    (parent_id,),
                )
                result = cursor.fetchone()
                if result:
                    parent_type = result[0]
                    cursor.execute(
                        """
                        INSERT INTO relationship_types (child_id, parent_id, parent_type)
                        VALUES (?, ?, ?)
                        """,
                        (child_id, parent_id, parent_type),
                    )

    except Exception as e:
        logger.error(f"Error updating relationship tables: {e}")
        logger.error(f"Child ID: {child_id}, Parent IDs: {parent_ids}")
        raise


def _update_user_email_map(conn: sqlite3.Connection) -> None:
    """Update the user_email_map table with current User objects.
    Called internally by update_sf_db_with_csv when User objects are updated.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO user_email_map (email, user_id)
        SELECT json_extract(data, '$.Email'), id
        FROM salesforce_objects
        WHERE object_type = 'User'
        AND json_extract(data, '$.Email') IS NOT NULL
        """
    )


def update_sf_db_with_csv(
    object_type: str,
    csv_download_path: str,
    delete_csv_after_use: bool = True,
) -> list[str]:
    """Update the SF DB with a CSV file using SQLite storage."""
    updated_ids = []

    # Use IMMEDIATE to get a write lock at the start of the transaction
    with get_db_connection("IMMEDIATE") as conn:
        cursor = conn.cursor()

        with open(csv_download_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "Id" not in row:
                    logger.warning(
                        f"Row {row} does not have an Id field in {csv_download_path}"
                    )
                    continue
                id = row["Id"]
                parent_ids = set()
                field_to_remove: set[str] = set()

                # Process relationships and clean data
                for field, value in row.items():
                    if validate_salesforce_id(value) and field != "Id":
                        parent_ids.add(value)
                        field_to_remove.add(field)
                    if not value:
                        field_to_remove.add(field)

                # Remove unwanted fields
                for field in field_to_remove:
                    if field != "LastModifiedById":
                        del row[field]

                # Update main object data
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO salesforce_objects (id, object_type, data)
                    VALUES (?, ?, ?)
                    """,
                    (id, object_type, json.dumps(row)),
                )

                # Update relationships using the same connection
                _update_relationship_tables(conn, id, parent_ids)
                updated_ids.append(id)

        # If we're updating User objects, update the email map
        if object_type == "User":
            _update_user_email_map(conn)

        conn.commit()

    if delete_csv_after_use:
        # Remove the csv file after it has been used
        # to successfully update the db
        os.remove(csv_download_path)

    return updated_ids


def get_child_ids(parent_id: str) -> set[str]:
    """Get all child IDs for a given parent ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Force index usage with INDEXED BY
        cursor.execute(
            "SELECT child_id FROM relationships INDEXED BY idx_parent_id WHERE parent_id = ?",
            (parent_id,),
        )
        child_ids = {row[0] for row in cursor.fetchall()}
    return child_ids


def get_type_from_id(object_id: str) -> str | None:
    """Get the type of an object from its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT object_type FROM salesforce_objects WHERE id = ?", (object_id,)
        )
        result = cursor.fetchone()
        if not result:
            logger.warning(f"Object ID {object_id} not found")
            return None
        return result[0]


def get_record(
    object_id: str, object_type: str | None = None
) -> SalesforceObject | None:
    """Retrieve the record and return it as a SalesforceObject."""
    if object_type is None:
        object_type = get_type_from_id(object_id)
        if not object_type:
            return None

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM salesforce_objects WHERE id = ?", (object_id,))
        result = cursor.fetchone()
        if not result:
            logger.warning(f"Object ID {object_id} not found")
            return None

        data = json.loads(result[0])
        return SalesforceObject(id=object_id, type=object_type, data=data)


def find_ids_by_type(object_type: str) -> list[str]:
    """Find all object IDs for rows of the specified type."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM salesforce_objects WHERE object_type = ?", (object_type,)
        )
        return [row[0] for row in cursor.fetchall()]


def get_affected_parent_ids_by_type(
    updated_ids: list[str],
    parent_types: list[str],
    batch_size: int = 500,
) -> Iterator[tuple[str, set[str]]]:
    """Get IDs of objects that are of the specified parent types and are either in the
    updated_ids or have children in the updated_ids. Yields tuples of (parent_type, affected_ids).
    """
    # SQLite typically has a limit of 999 variables
    updated_ids_batches = batch_list(updated_ids, batch_size)
    updated_parent_ids: set[str] = set()

    with get_db_connection() as conn:
        cursor = conn.cursor()

        for batch_ids in updated_ids_batches:
            batch_ids = list(set(batch_ids) - updated_parent_ids)
            if not batch_ids:
                continue
            id_placeholders = ",".join(["?" for _ in batch_ids])

            for parent_type in parent_types:
                affected_ids: set[str] = set()

                # Get directly updated objects of parent types - using index on object_type
                cursor.execute(
                    f"""
                    SELECT id FROM salesforce_objects
                    WHERE id IN ({id_placeholders})
                    AND object_type = ?
                    """,
                    batch_ids + [parent_type],
                )
                affected_ids.update(row[0] for row in cursor.fetchall())

                # Get parent objects of updated objects - using optimized relationship_types table
                cursor.execute(
                    f"""
                    SELECT DISTINCT parent_id
                    FROM relationship_types
                    INDEXED BY idx_relationship_types_lookup
                    WHERE parent_type = ?
                    AND child_id IN ({id_placeholders})
                    """,
                    [parent_type] + batch_ids,
                )
                affected_ids.update(row[0] for row in cursor.fetchall())

                # Remove any parent IDs that have already been processed
                new_affected_ids = affected_ids - updated_parent_ids
                # Add the new affected IDs to the set of updated parent IDs
                updated_parent_ids.update(new_affected_ids)

                if new_affected_ids:
                    yield parent_type, new_affected_ids


def has_at_least_one_object_of_type(object_type: str) -> bool:
    """Check if there is at least one object of the specified type in the database.

    Args:
        object_type: The Salesforce object type to check

    Returns:
        bool: True if at least one object exists, False otherwise
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM salesforce_objects WHERE object_type = ?",
            (object_type,),
        )
        count = cursor.fetchone()[0]
        return count > 0


# NULL_ID_STRING is used to indicate that the user ID was queried but not found
# As opposed to None because it has yet to be queried at all
NULL_ID_STRING = "N/A"


def get_user_id_by_email(email: str) -> str | None:
    """Get the Salesforce User ID for a given email address.

    Args:
        email: The email address to look up

    Returns:
        A tuple of (was_found, user_id):
            - was_found: True if the email exists in the table, False if not found
            - user_id: The Salesforce User ID if exists, None otherwise
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_email_map WHERE email = ?", (email,))
        result = cursor.fetchone()
        if result is None:
            return None
        return result[0]


def update_email_to_id_table(email: str, id: str | None) -> None:
    """Update the email to ID map table with a new email and ID."""
    id_to_use = id or NULL_ID_STRING
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_email_map (email, user_id) VALUES (?, ?)",
            (email, id_to_use),
        )
        conn.commit()
