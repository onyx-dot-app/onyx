import csv
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from typing import cast

from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.salesforce.utils import ACCOUNT_OBJECT_TYPE
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.connectors.salesforce.utils import NAME_FIELD
from onyx.connectors.salesforce.utils import SalesforceObject
from onyx.connectors.salesforce.utils import USER_OBJECT_TYPE
from onyx.connectors.salesforce.utils import validate_salesforce_id
from onyx.utils.logger import setup_logger
from shared_configs.utils import batch_list


logger = setup_logger()


class OnyxSalesforceSQLite:
    """Notes on context management using 'with self.conn':

    Does autocommit / rollback on exit.
    Does NOT close on exit! .close must be called explicitly.
    """

    # NOTE(rkuo): this string could probably occur naturally. A more unique value
    # might be appropriate here.
    NULL_ID_STRING = "N/A"

    def __init__(self, filename: str, isolation_level: str | None = None):
        self.filename = filename
        self.isolation_level = isolation_level
        self._conn: sqlite3.Connection | None = None

        # this is only set on connection. This variable does not change
        # when a new db is initialized with this class.
        self._existing_db = True

    def __del__(self) -> None:
        self.close()

    @property
    def file_size(self) -> int:
        """Returns -1 if the file does not exist."""
        if not self.filename:
            return -1

        if not os.path.exists(self.filename):
            return -1

        file_path = Path(self.filename)
        return file_path.stat().st_size

    def connect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

        self._existing_db = os.path.exists(self.filename)

        # make the path if it doesn't already exist
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        conn = sqlite3.connect(self.filename, timeout=60.0)
        if self.isolation_level is not None:
            conn.isolation_level = self.isolation_level

        self._conn = conn

    def close(self) -> None:
        if self._conn is None:
            return

        self._conn.close()
        self._conn = None

    def cursor(self) -> sqlite3.Cursor:
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        return self._conn.cursor()

    def flush(self) -> None:
        """We're using SQLite in WAL mode sometimes. To flush to the DB we have to
        call this."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(FULL)")

    def apply_schema(self) -> None:
        """Initialize the SQLite database with required tables if they don't exist.

        Non-destructive operation.
        """
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        start = time.monotonic()

        with self._conn:
            cursor = self._conn.cursor()

            if self._existing_db:
                file_path = Path(self.filename)
                file_size = file_path.stat().st_size
                logger.info(f"init_db - found existing sqlite db: len={file_size}")
            else:
                # NOTE(rkuo): why is this only if the db doesn't exist?

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

            # NOTE(rkuo): this seems completely redundant with relationship_types
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
            def create_index_if_not_exists(
                index_name: str, create_statement: str
            ) -> None:
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

            elapsed = time.monotonic() - start
            logger.info(f"init_db - create tables and indices: elapsed={elapsed:.2f}")

            # Analyze tables to help query planner
            # NOTE(rkuo): skip ANALYZE - it takes too long and we likely don't have
            # complicated queries that need this
            # start = time.monotonic()
            # cursor.execute("ANALYZE relationships")
            # cursor.execute("ANALYZE salesforce_objects")
            # cursor.execute("ANALYZE relationship_types")
            # cursor.execute("ANALYZE user_email_map")
            # elapsed = time.monotonic() - start
            # logger.info(f"init_db - analyze: elapsed={elapsed:.2f}")

            # If database already existed but user_email_map needs to be populated
            start = time.monotonic()
            cursor.execute("SELECT COUNT(*) FROM user_email_map")
            elapsed = time.monotonic() - start
            logger.info(f"init_db - count user_email_map: elapsed={elapsed:.2f}")

            start = time.monotonic()
            if cursor.fetchone()[0] == 0:
                OnyxSalesforceSQLite._update_user_email_map(cursor)
            elapsed = time.monotonic() - start
            logger.info(f"init_db - update_user_email_map: elapsed={elapsed:.2f}")

    def get_user_id_by_email(self, email: str) -> str | None:
        """Get the Salesforce User ID for a given email address.

        Args:
            email: The email address to look up

        Returns:
            A tuple of (was_found, user_id):
                - was_found: True if the email exists in the table, False if not found
                - user_id: The Salesforce User ID if exists, None otherwise
        """
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT user_id FROM user_email_map WHERE email = ?", (email,)
            )
            result = cursor.fetchone()
            if result is None:
                return None
            return result[0]

    def update_email_to_id_table(self, email: str, id: str | None) -> None:
        """Update the email to ID map table with a new email and ID."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        id_to_use = id or self.NULL_ID_STRING
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_email_map (email, user_id) VALUES (?, ?)",
                (email, id_to_use),
            )

    def log_stats(self) -> None:
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cache_pages = self._conn.execute("PRAGMA cache_size").fetchone()[0]
            page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
            if cache_pages >= 0:
                cache_bytes = cache_pages * page_size
            else:
                cache_bytes = abs(cache_pages * 1024)
            logger.info(
                f"SQLite stats: sqlite_version={sqlite3.sqlite_version} "
                f"cache_pages={cache_pages} "
                f"page_size={page_size} "
                f"cache_bytes={cache_bytes}"
            )

    # get_changed_parent_ids_by_type_2 replaces this
    def get_changed_parent_ids_by_type(
        self,
        changed_ids: list[str],
        parent_types: set[str],
        batch_size: int = 500,
    ) -> Iterator[tuple[str, str, int]]:
        """Get IDs of objects that are of the specified parent types and are either in the
        updated_ids or have children in the updated_ids. Yields tuples of (parent_type, affected_ids, num_examined).

        NOTE(rkuo): This function used to have some interesting behavior ... it created batches of id's
        and yielded back a list once for each parent type within that batch.

        There's no need to expose the details of the internal batching to the caller, so
        we're now yielding once per changed parent.
        """
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        updated_parent_ids: set[str] = (
            set()
        )  # dedupes parent id's that have already been yielded

        # SQLite typically has a limit of 999 variables
        num_examined = 0
        updated_ids_batches = batch_list(changed_ids, batch_size)

        with self._conn:
            cursor = self._conn.cursor()

            for batch_ids in updated_ids_batches:
                num_examined += len(batch_ids)

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
                    newly_affected_ids = affected_ids - updated_parent_ids
                    # Add the new affected IDs to the set of updated parent IDs
                    if newly_affected_ids:
                        # Yield each newly affected ID individually
                        for parent_id in newly_affected_ids:
                            yield parent_type, parent_id, num_examined

                        updated_parent_ids.update(newly_affected_ids)

    def get_changed_parent_ids_by_type_2(
        self,
        changed_ids: dict[str, str],
        parent_types: set[str],
        parent_relationship_fields_by_type: dict[str, dict[str, list[str]]],
        prefix_to_type: dict[str, str],
    ) -> Iterator[tuple[str, str, int]]:
        """
        This function yields back any changed parent id's based on
        a relationship lookup.

        Yields tuples of (changed_id, parent_type, num_examined)
        changed_id is the id of the changed parent record
        parent_type is the object table/type of the id (based on a prefix lookup)
        num_examined is an integer which signifies our progress through the changed_id's dict

        changed_ids is a list of all id's that changed, both parent and children.
        parent

        This is much simpler than get_changed_parent_ids_by_type.

        TODO(rkuo): for common entities, the first 3 chars identify the object type
        see https://help.salesforce.com/s/articleView?id=000385203&type=1
        """
        changed_parent_ids: set[str] = (
            set()
        )  # dedupes parent id's that have already been yielded

        # SQLite typically has a limit of 999 variables
        num_examined = 0

        for changed_id, changed_type in changed_ids.items():
            num_examined += 1

            # if we yielded this id already, continue
            if changed_id in changed_parent_ids:
                continue

            # if this id is a parent type, yield it directly
            if changed_type in parent_types:
                yield changed_id, changed_type, num_examined
                changed_parent_ids.add(changed_id)
                continue

            # if this id is a child type, then check the columns
            # that relate it to the parent id and yield those ids
            # NOTE: Although unlikely, id's yielded in this way may not be of the
            # type we're interested in, so the caller must be prepared
            # for the id to not be present

            # get the child id record
            sf_object = self.get_record(changed_id, changed_type)
            if not sf_object:
                continue

            # get the fields that contain parent id's
            parent_relationship_fields = parent_relationship_fields_by_type[
                changed_type
            ]
            for field_name, _ in parent_relationship_fields.items():
                if field_name not in sf_object.data:
                    logger.warning(f"{field_name=} not in data for {changed_type=}!")
                    continue

                parent_id = cast(str, sf_object.data[field_name])
                parent_id_prefix = parent_id[:3]

                if parent_id_prefix not in prefix_to_type:
                    logger.warning(
                        f"Could not lookup type for prefix: {parent_id_prefix=}"
                    )
                    continue

                parent_type = prefix_to_type[parent_id_prefix]
                if parent_type not in parent_types:
                    continue

                yield parent_id, parent_type, num_examined
                changed_parent_ids.add(parent_id)
                break

    def object_type_count(self, object_type: str) -> int:
        """Check if there is at least one object of the specified type in the database.

        Args:
            object_type: The Salesforce object type to check

        Returns:
            bool: True if at least one object exists, False otherwise
        """
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM salesforce_objects WHERE object_type = ?",
                (object_type,),
            )
            count = cursor.fetchone()[0]
            return count

    @staticmethod
    def normalize_record(
        original_record: dict[str, Any],
        remove_ids: bool = True,
    ) -> tuple[dict[str, Any], set[str]]:
        """Takes a dict of field names to values and removes fields
        we don't want.

        This means most parent id field's and any fields with null values.

        Return a json string and a list of parent_id's in the record.
        """
        parent_ids: set[str] = set()
        fields_to_remove: set[str] = set()

        record = original_record.copy()

        for field, value in record.items():
            # remove empty fields
            if not value:
                fields_to_remove.add(field)
                continue

            if field == "attributes":
                fields_to_remove.add(field)
                continue

            # remove salesforce id's (and add to parent id set)
            if (
                field != ID_FIELD
                and isinstance(value, str)
                and validate_salesforce_id(value)
            ):
                parent_ids.add(value)
                if remove_ids:
                    fields_to_remove.add(field)
                continue

            # this field is real data, leave it alone

        # Remove unwanted fields
        for field in fields_to_remove:
            if field != "LastModifiedById":
                del record[field]

        return record, parent_ids

    def update_from_csv(
        self, object_type: str, csv_download_path: str, remove_ids: bool = True
    ) -> list[str]:
        """Update the SF DB with a CSV file using SQLite storage."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        # some customers need this to be larger than the default 128KB, go with 16MB
        csv.field_size_limit(16 * 1024 * 1024)

        updated_ids = []

        with self._conn:
            cursor = self._conn.cursor()

            with open(csv_download_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                uncommitted_rows = 0
                for row in reader:
                    if ID_FIELD not in row:
                        logger.warning(
                            f"Row {row} does not have an {ID_FIELD} field in {csv_download_path}"
                        )
                        continue

                    row_id = row[ID_FIELD]

                    normalized_record, parent_ids = (
                        OnyxSalesforceSQLite.normalize_record(row, remove_ids)
                    )
                    normalized_record_json_str = json.dumps(normalized_record)

                    # Update main object data
                    # NOTE(rkuo): looks like we take a list and dump it as json into the db
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO salesforce_objects (id, object_type, data)
                        VALUES (?, ?, ?)
                        """,
                        (row_id, object_type, normalized_record_json_str),
                    )

                    # Update relationships using the same connection
                    OnyxSalesforceSQLite._update_relationship_tables(
                        cursor, row_id, parent_ids
                    )
                    updated_ids.append(row_id)

                    # periodically commit or else memory will balloon
                    uncommitted_rows += 1
                    if uncommitted_rows >= 1024:
                        self._conn.commit()
                        uncommitted_rows = 0

            # If we're updating User objects, update the email map
            if object_type == USER_OBJECT_TYPE:
                OnyxSalesforceSQLite._update_user_email_map(cursor)

        return updated_ids

    def get_child_ids(self, parent_id: str) -> set[str]:
        """Get all child IDs for a given parent ID."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()

            # Force index usage with INDEXED BY
            cursor.execute(
                "SELECT child_id FROM relationships INDEXED BY idx_parent_id WHERE parent_id = ?",
                (parent_id,),
            )
            child_ids = {row[0] for row in cursor.fetchall()}
        return child_ids

    def get_type_from_id(self, object_id: str) -> str | None:
        """Get the type of an object from its ID."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT object_type FROM salesforce_objects WHERE id = ?", (object_id,)
            )
            result = cursor.fetchone()
            if not result:
                logger.warning(f"Object ID {object_id} not found")
                return None
            return result[0]

    def get_record(
        self, object_id: str, object_type: str | None = None, isChild: bool = False
    ) -> SalesforceObject | None:
        """Retrieve the record and return it as a SalesforceObject."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        if object_type is None:
            object_type = self.get_type_from_id(object_id)
            if not object_type:
                return None

        with self._conn:
            cursor = self._conn.cursor()
            # Get the object data and account data
            if object_type == ACCOUNT_OBJECT_TYPE or isChild:
                cursor.execute(
                    "SELECT data FROM salesforce_objects WHERE id = ?", (object_id,)
                )
            else:
                cursor.execute(
                    "SELECT pso.data, r.parent_id as parent_id, sso.object_type FROM salesforce_objects pso \
                        LEFT JOIN relationships r on r.child_id = pso.id \
                        LEFT JOIN salesforce_objects sso on r.parent_id = sso.id \
                        WHERE pso.id = ? ",
                    (object_id,),
                )
            result = cursor.fetchall()
            if not result:
                logger.warning(f"Object ID {object_id} not found")
                return None

            data = json.loads(result[0][0])

            if object_type != ACCOUNT_OBJECT_TYPE:

                # convert any account ids of the relationships back into data fields, with name
                for row in result:

                    # the following skips Account objects.
                    if len(row) < 3:
                        continue

                    if row[1] and row[2] and row[2] == ACCOUNT_OBJECT_TYPE:
                        data["AccountId"] = row[1]
                        cursor.execute(
                            "SELECT data FROM salesforce_objects WHERE id = ?",
                            (row[1],),
                        )
                        account_data = json.loads(cursor.fetchone()[0])
                        data[ACCOUNT_OBJECT_TYPE] = account_data.get(NAME_FIELD, "")

            return SalesforceObject(id=object_id, type=object_type, data=data)

    def find_ids_by_type(self, object_type: str) -> list[str]:
        """Find all object IDs for rows of the specified type."""
        if self._conn is None:
            raise RuntimeError("Database connection is closed")

        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT id FROM salesforce_objects WHERE object_type = ?",
                (object_type,),
            )
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def _update_relationship_tables(
        cursor: sqlite3.Cursor, child_id: str, parent_ids: set[str]
    ) -> None:
        """Given a child id and a set of parent id's, updates the
        relationships of the child to the parents in the db and removes old relationships.

        Args:
            conn: The database connection to use (must be in a transaction)
            child_id: The ID of the child record
            parent_ids: Set of parent IDs to link to
        """

        try:
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
                    [(child_id, parent_id) for parent_id in parent_ids_to_remove],
                )
                # Also remove from relationship_types
                cursor.executemany(
                    "DELETE FROM relationship_types WHERE child_id = ? AND parent_id = ?",
                    [(child_id, parent_id) for parent_id in parent_ids_to_remove],
                )

            # Add new relationships
            if parent_ids_to_add:
                # First add to relationships table
                cursor.executemany(
                    "INSERT INTO relationships (child_id, parent_id) VALUES (?, ?)",
                    [(child_id, parent_id) for parent_id in parent_ids_to_add],
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

        except Exception:
            logger.exception(
                f"Error updating relationship tables: child_id={child_id} parent_ids={parent_ids}"
            )
            raise

    @staticmethod
    def _update_user_email_map(cursor: sqlite3.Cursor) -> None:
        """Update the user_email_map table with current User objects.
        Called internally by update_sf_db_with_csv when User objects are updated.
        """

        cursor.execute(
            """
            INSERT OR REPLACE INTO user_email_map (email, user_id)
            SELECT json_extract(data, '$.Email'), id
            FROM salesforce_objects
            WHERE object_type = 'User'
            AND json_extract(data, '$.Email') IS NOT NULL
            """
        )

    def make_basic_expert_info_from_record(
        self,
        sf_object: SalesforceObject,
    ) -> BasicExpertInfo | None:
        """Parses record for LastModifiedById and returns BasicExpertInfo
        of the user if possible."""
        object_dict: dict[str, Any] = sf_object.data
        if not (last_modified_by_id := object_dict.get("LastModifiedById")):
            logger.warning(f"No LastModifiedById found for {sf_object.id}")
            return None
        if not (last_modified_by := self.get_record(last_modified_by_id)):
            logger.warning(f"No LastModifiedBy found for {last_modified_by_id}")
            return None

        try:
            expert_info = BasicExpertInfo.from_dict(last_modified_by.data)
        except Exception:
            return None

        return expert_info
