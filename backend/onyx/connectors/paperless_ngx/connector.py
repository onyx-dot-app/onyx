import logging
import time
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import requests
from typing_extensions import override

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection

# Import necessary interfaces

logger = logging.getLogger(__name__)

DOCUMENTS_ENDPOINT = "/api/documents/"
TAGS_ENDPOINT = "/api/tags/"
USERS_ENDPOINT = "/api/users/"
CORRESPONDENTS_ENDPOINT = "/api/correspondents/"
DOCUMENT_TYPES_ENDPOINT = "/api/document_types/"
# CUSTOM_FIELDS_ENDPOINT = "/api/custom_fields/"


class PaperlessNgxConnector(LoadConnector, PollConnector, SlimConnector):
    """
    Connector for fetching documents from a Paperless-ngx instance.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        start_date: Optional[str] = None,
        ingest_tags: Optional[str] = None,
        ingest_usernames: Optional[str] = None,
        ingest_noowner: Optional[bool] = False,
    ) -> None:
        self.api_url = api_url

        if not self.api_url:
            self.api_url = os.environ.get("PAPERLESS_API_URL")
            logger.debug("Loaded API URL from environment variables")
        else:
            logger.debug("Using web user-provided API URL")

        if not self.api_url:
            raise ConnectorValidationError(
                "API URL not found in environment variables or settings."
            )

        # Allowed start_date formats:
        # - yyyy-mm-dd
        # - mm/dd/yyyy
        # - dd/mm/yyyy
        # - mm-dd-yyyy
        # - dd-mm-yyyy
        # - yyyy/mm/dd
        # - dd.mm.yyyy
        # - mm.dd.yyyy
        self.start_date: Optional[str] = None
        if start_date:
            try:
                for fmt in [
                    "%Y-%m-%d",
                    "%m/%d/%Y",
                    "%d/%m/%Y",
                    "%m-%d-%Y",
                    "%d-%m-%Y",
                    "%Y/%m/%d",
                    "%d.%m.%Y",
                    "%m.%d.%Y",
                ]:
                    try:
                        parsed_date = datetime.strptime(start_date, fmt)
                        self.start_date = parsed_date.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
                if not hasattr(self, "start_date"):
                    raise ValueError("Could not parse date with any format")
            except ValueError as e:
                logger.warning(
                    f"Could not parse start_date: {start_date}. Using None. Error: {e}"
                )
                raise ConnectorValidationError(
                    f"Could not parse start_date: {start_date}. Error: {e}"
                )

        try:
            self.ingest_tags: List[str] = (
                [tag.strip() for tag in ingest_tags.split(",")] if ingest_tags else []
            )
        except ValueError as e:
            raise ConnectorValidationError(
                f"Could not parse ingest_tags: {ingest_tags}. Error: {e}"
            )

        try:
            self.ingest_usernames: List[str] = (
                [username.strip() for username in ingest_usernames.split(",")]
                if ingest_usernames
                else []
            )
        except ValueError as e:
            raise ConnectorValidationError(
                f"Could not parse ingest_usernames: {ingest_usernames}. Error: {e}"
            )

        self.ingest_noowner = ingest_noowner

        logger.info("Initialized PaperlessNgxConnector")

    @override
    def load_credentials(self, credentials: Dict[str, Any]) -> None:
        # """
        # Loads Token from environment variables if not set with web user-provided credentials.

        self.auth_token = credentials["paperless_ngx_auth_token"]

        if not self.auth_token:
            self.auth_token = os.environ.get("PAPERLESS_AUTH_TOKEN")
            logger.debug("Loaded auth token from environment variables")
        else:
            logger.debug("Using web user-provided auth token")

        if not self.auth_token:
            raise PermissionError(
                "Auth token not found in environment variables or settings."
            )

    def _get_headers(self) -> Dict[str, str]:
        """Returns authentication headers."""
        if not self.auth_token:
            raise PermissionError("API key not loaded.")
        return {
            "Authorization": f"Token {self.auth_token}",
            "Accept": "application/json",
        }

    def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Helper function to make paginated requests to the Paperless-ngx API.

        Args:
            endpoint: The API endpoint path (e.g., 'api/documents/').
            params: Optional dictionary of query parameters.

        Returns:
            A list of all results fetched from the paginated endpoint.
        """
        if not self.api_url:
            raise ValueError("API URL not configured.")

        results = []
        url = f"{self.api_url}{endpoint}"
        headers = self._get_headers()

        # Initialize parameters if None

        # Initialize parameters if None
        if params is None:
            params = {}

        while url:
            try:
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
                data = response.json()

                results.extend(data.get("results", []))
                url = data.get("next")  # Get URL for the next page
                params = None  # Parameters are included in the 'next' URL

            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching data from Paperless-ngx API: {e}")
                raise ConnectionError(f"Failed to connect to Paperless-ngx API: {e}")

        return results

    def _get_docs(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves documents based on configured filters (tags, usernames, no owner) and optional date range.

        Args:
            start_date: Optional start date in ISO format (YYYY-MM-DD)
            end_date: Optional end date in ISO format (YYYY-MM-DD)

        This function uses the Paperless-ngx API to filter documents by:
        1. Tags (using tags__id__in parameter)
        2. Owners/users (using owner__id__in parameter)
        3. Documents with no owner (using owner__isnull parameter)
        4. Date ranges (using created__date__gte and created__date__lte)

        Returns:
            A list of document data dictionaries from the Paperless API
        """

        # update attribute lists so they can be added as needed for filters and when documents parsed
        self.all_tags = self._make_request(TAGS_ENDPOINT)
        self.all_users = self._make_request(USERS_ENDPOINT)
        self.all_correspondents = self._make_request(CORRESPONDENTS_ENDPOINT)
        self.all_doc_types = self._make_request(DOCUMENT_TYPES_ENDPOINT)
        # self.all_custom_fields = self._make_request(CUSTOM_FIELDS_ENDPOINT)

        # Build base parameters dict with date filters
        params = {}
        if start_date:
            params["created__date__gte"] = start_date
        elif self.start_date:
            params["created__date__gte"] = self.start_date

        if end_date:
            params["created__date__lte"] = end_date

        # Get tag IDs if tags are specified
        tag_ids = []
        if self.ingest_tags:
            logger.debug(f"Finding tag IDs for: {self.ingest_tags}")
            tag_name_to_id = {tag["name"].lower(): tag["id"] for tag in self.all_tags}

            for tag_name in self.ingest_tags:
                tag_name_lower = tag_name.lower()
                if tag_name_lower in tag_name_to_id:
                    tag_ids.append(tag_name_to_id[tag_name_lower])
                else:
                    logger.warning(
                        f"Tag '{tag_name}' not found in Paperless-ngx instance"
                    )

            if tag_ids:
                params["tags__id__in"] = ",".join(str(tag_id) for tag_id in tag_ids)

        # Get user IDs if usernames are specified
        user_ids = []
        if self.ingest_usernames:
            logger.debug(f"Finding user IDs for: {self.ingest_usernames}")
            username_to_id = {
                user["username"].lower(): user["id"] for user in self.all_users
            }

            for username in self.ingest_usernames:
                username_lower = username.lower()
                if username_lower in username_to_id:
                    user_ids.append(username_to_id[username_lower])
                else:
                    logger.warning(
                        f"User '{username}' not found in Paperless-ngx instance"
                    )

            if user_ids:
                params["owner__id__in"] = ",".join(str(user_id) for user_id in user_ids)

        # Handle different filtering combinations
        if self.ingest_tags and not self.ingest_usernames:
            # Only filter by tags
            logger.debug(f"Retrieving documents with tags: {self.ingest_tags}")
            if not tag_ids:
                logger.warning("No valid tags found, returning empty result")
                return []
            docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)
        elif self.ingest_usernames and not self.ingest_tags:
            # Filter by users with optional no-owner inclusion
            if not user_ids and not self.ingest_noowner:
                logger.warning(
                    "No valid users found and no-owner not enabled, returning empty result"
                )
                return []

            if self.ingest_noowner:
                logger.debug(
                    f"Retrieving documents for users: {self.ingest_usernames} and documents with no owner"
                )
                # We need to make two requests and combine the results
                user_docs = []
                if user_ids:
                    user_docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)

                # Make a separate request for no-owner documents
                noowner_params = params.copy()
                if "owner__id__in" in noowner_params:
                    del noowner_params["owner__id__in"]
                noowner_params["owner__isnull"] = "true"
                noowner_docs = self._make_request(
                    DOCUMENTS_ENDPOINT, params=noowner_params
                )

                # Combine and deduplicate
                seen_ids = set()
                docs = []
                for doc_list in [user_docs, noowner_docs]:
                    for doc in doc_list:
                        doc_id = doc.get("id")
                        if doc_id and doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            docs.append(doc)
            else:
                logger.debug(f"Retrieving documents for users: {self.ingest_usernames}")
                docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)
        elif self.ingest_tags and self.ingest_usernames:
            # Combined filter: documents with specified tags AND (specified users OR no owner if enabled)
            if not tag_ids:
                logger.warning("No valid tags found, returning empty result")
                return []

            if not user_ids and not self.ingest_noowner:
                logger.warning(
                    "No valid users found and no-owner not enabled, returning empty result"
                )
                return []

            if self.ingest_noowner:
                logger.debug(
                    f"Retrieving documents with tags: {self.ingest_tags} "
                    + f"for users: {self.ingest_usernames} and documents with no owner"
                )
                # We need to make two requests and combine the results
                user_docs = []
                if user_ids:
                    user_docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)

                # Make a separate request for no-owner documents
                noowner_params = params.copy()
                if "owner__id__in" in noowner_params:
                    del noowner_params["owner__id__in"]
                noowner_params["owner__isnull"] = "true"
                noowner_docs = self._make_request(
                    DOCUMENTS_ENDPOINT, params=noowner_params
                )

                # Combine and deduplicate
                seen_ids = set()
                docs = []
                for doc_list in [user_docs, noowner_docs]:
                    for doc in doc_list:
                        doc_id = doc.get("id")
                        if doc_id and doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            docs.append(doc)
            else:
                logger.debug(
                    f"Retrieving documents with tags: {self.ingest_tags} for users: {self.ingest_usernames}"
                )
                docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)
        else:
            # No specific filters, get all documents
            logger.debug("No filters specified, retrieving all documents")
            docs = self._make_request(DOCUMENTS_ENDPOINT, params=params)

        logger.debug(f"Retrieved {len(docs)} documents matching the specified filters")
        return docs

    def _parse_document(self, doc_data: Dict[str, Any]) -> Optional[Document]:
        """
        Converts a Paperless-ngx document API response item into an Onyx Document.
        """
        doc_id = doc_data.get("id")
        title = doc_data.get("title")
        content = doc_data.get("content")
        added_timestamp_str = doc_data.get("added")
        modified_timestamp_str = doc_data.get("modified")
        image_file_name = doc_data.get("archived_file_name")

        # Defensive checks and parse
        if (
            doc_id is None
            or title is None
            or content is None
            or not modified_timestamp_str
        ):
            logger.warning(
                f"Skipping document due to missing essential data: {doc_data}"
            )
            return None

        base_url = (
            self.api_url.split("/api/")[0]
            if self.api_url and "/api/" in self.api_url
            else (self.api_url or "")
        )
        uri = f"{base_url}/documents/{doc_id}/details"
        file_uri = f"{base_url}/api/documents/{doc_id}/preview/"

        try:
            updated_at = datetime.fromisoformat(
                modified_timestamp_str.replace("Z", "+00:00")
            )
            # Ensure datetime is in UTC
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                f"Could not parse timestamp for document {doc_id}: {modified_timestamp_str}"
            )
            updated_at = datetime.now(timezone.utc)

        # Only allow str or List[str] in metadata => coerce all metadata fields to str or list[str]
        metadata: Dict[str, Union[str, List[str]]] = {
            "source": DocumentSource.PAPERLESS_NGX.value,
            "added_date": str(added_timestamp_str),
            "uri": uri,
            "file_uri": file_uri,
            "tag_ids": ",".join(map(str, doc_data.get("tags", []))),
            "tag_names": ",".join(
                map(
                    str,
                    [
                        tag["name"]
                        for tag in self.all_tags
                        if tag["id"] in doc_data.get("tags", [])
                    ],
                )
            ),
            "correspondent_id": (
                ""
                if doc_data.get("correspondent") is None
                else str(doc_data.get("correspondent"))
            ),
            "correspondent_name": next(
                (
                    corr["name"]
                    for corr in self.all_correspondents
                    if corr["id"] == doc_data.get("correspondent")
                ),
                "",
            ),
            "owner_id": (
                "" if doc_data.get("owner") is None else str(doc_data.get("owner"))
            ),
            "owner_name": next(
                (
                    user["username"]
                    for user in self.all_users
                    if user["id"] == doc_data.get("owner")
                ),
                "",
            ),
            "document_type_id": (
                ""
                if doc_data.get("document_type") is None
                else str(doc_data.get("document_type"))
            ),
            "document_type_name": next(
                (
                    doc_type["name"]
                    for doc_type in self.all_doc_types
                    if doc_type["id"] == doc_data.get("document_type")
                ),
                "",
            ),
            "page_count": (
                ""
                if doc_data.get("page_count") is None
                else str(doc_data.get("page_count"))
            ),
            "created_date": doc_data.get("created_date", ""),
            "mime_type": doc_data.get("mime_type", ""),
            "archive_serial_number": (
                ""
                if doc_data.get("archive_serial_number") is None
                else str(doc_data.get("archive_serial_number"))
            ),
            "notes": "\n".join(
                [
                    f"{note.get('note', '')} (created at {note.get('created', '')} by "
                    + f"{next((user['username'] for user in self.all_users if user['id']==note.get('user', {}).get('id')), '')})"
                    for note in doc_data.get("notes", [])
                ]
            ),
            # TODO: add custom fields
            #       add original_file_name?
            #       handle images?
            #       generate shareable link?
        }

        sections: List[Union[TextSection, ImageSection]] = [
            TextSection(link=uri, text=content, image_file_name=image_file_name)
        ]

        return Document(
            id=str(doc_id),
            sections=sections,
            source=DocumentSource.PAPERLESS_NGX,
            semantic_identifier=title,
            metadata=metadata,
            doc_updated_at=updated_at,
            title=title,
        )

    @override
    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Loads all documents from the Paperless-ngx instance.
        """
        all_doc_data = self._get_docs()
        documents = []
        for doc_data in all_doc_data:
            doc = self._parse_document(doc_data)
            if doc:
                documents.append(doc)

        logger.info(f"Loaded {len(documents)} documents from Paperless-ngx.")
        yield documents

    @override
    def poll_source(self, start: float, end: float) -> GenerateDocumentsOutput:
        """
        Polls for documents modified between start and end.
        Args:
            start: Unix timestamp for interval start.
            end: Unix timestamp for interval end.
        """
        start_dt = datetime.fromtimestamp(start, timezone.utc)
        end_dt = datetime.fromtimestamp(end, timezone.utc)

        # Format dates for API query in ISO format
        start_iso = start_dt.strftime("%Y-%m-%d")
        end_iso = end_dt.strftime("%Y-%m-%d")

        logger.info(
            f"Polling Paperless-ngx for documents modified between {start_iso} and {end_iso}."
        )

        updated_doc_data = self._get_docs(start_date=start_iso, end_date=end_iso)

        documents = []
        for doc_data in updated_doc_data:
            doc = self._parse_document(doc_data)
            if doc and doc.doc_updated_at:
                if start_dt < doc.doc_updated_at <= end_dt:
                    documents.append(doc)
                else:
                    logger.debug(
                        f"Document {doc.id} timestamp {doc.doc_updated_at} not in range {start_dt} - {end_dt}, filtering out."
                    )

        logger.info(
            f"Found {len(documents)} new/updated documents in Paperless-ngx in time range."
        )
        yield documents

    @override
    def retrieve_all_slim_documents(
        self,
        start: Optional[float] = None,
        end: Optional[float] = None,
        callback: Optional[Any] = None,
    ) -> GenerateSlimDocumentOutput:
        """
        Implements SlimConnector interface to fetch only document IDs.
        This is a lighter weight method to check if documents still exist.

        Args:
            start: Optional Unix timestamp for interval start.
            end: Optional Unix timestamp for interval end.
            callback: Optional callback for indexing heartbeat.

        Returns:
            Iterator of lists of SlimDocument objects.
        """
        logger.info("Retrieving slim document IDs from Paperless-ngx.")

        # Initialize date parameters
        start_iso = None
        end_iso = None

        # Apply date filtering if provided
        if start is not None:
            start_dt = datetime.fromtimestamp(start, timezone.utc)
            start_iso = start_dt.strftime("%Y-%m-%d")
            logger.info(f"Filtering slim documents from {start_iso}")

        if end is not None:
            end_dt = datetime.fromtimestamp(end, timezone.utc)
            end_iso = end_dt.strftime("%Y-%m-%d")
            logger.info(f"Filtering slim documents until {end_iso}")

        # Get only the IDs by making the request and extracting minimal information
        doc_data = self._get_docs(start_date=start_iso, end_date=end_iso)

        # Convert to SlimDocument objects
        slim_docs = []
        for item in doc_data:
            doc_id = item.get("id")
            if doc_id is not None:
                # Try to get the last_modified timestamp if available
                modified_timestamp_str = item.get("modified")
                doc_updated_at = None

                if modified_timestamp_str:
                    try:
                        doc_updated_at = datetime.fromisoformat(
                            modified_timestamp_str.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError, AttributeError):
                        logger.debug(
                            f"Could not parse timestamp for slim document {doc_id}"
                        )

                slim_docs.append(
                    SlimDocument(
                        id=str(doc_id),
                        perm_sync_data={
                            "source": DocumentSource.PAPERLESS_NGX,
                            "doc_updated_at": doc_updated_at,
                        },
                    )
                )

        logger.info(f"Retrieved {len(slim_docs)} slim documents from Paperless-ngx")
        yield slim_docs


# Development testing block
if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    # Configure logging to print to console
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logger.setLevel(logging.DEBUG)

    # --- Added for .env loading ---
    try:
        from dotenv import load_dotenv
    except ImportError:
        print(
            "Error: python-dotenv library not found. Please install it (`pip install python-dotenv`) to load .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load .env file from project root or current directory
    env_path = Path(".") / ".env"
    if not env_path.exists():
        # If not in CWD, try searching upwards (default dotenv behavior)
        load_dotenv()
    else:
        load_dotenv(dotenv_path=env_path)

    print("Attempting to load credentials from environment variables / .env file...")

    # Requires PAPERLESS_API_URL and PAPERLESS_AUTH_TOKEN env vars set for testing
    api_url = os.environ.get("PAPERLESS_API_URL")
    auth_token = os.environ.get("PAPERLESS_AUTH_TOKEN")

    if not api_url or not auth_token:
        print(
            "Error: PAPERLESS_API_URL and/or PAPERLESS_AUTH_TOKEN not found in environment or .env file.",
            file=sys.stderr,
        )
        print(
            "Please ensure they are set in your .env file at the project root or exported.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Mask the API key partially for logging, show URL
        masked_key = (
            f"{auth_token[:4]}...{auth_token[-4:]}"
            if len(auth_token) > 8
            else "********"
        )
        print(
            f"Testing PaperlessNgxConnector with URL: {api_url} and Key: {masked_key}"
        )
        test_connector = PaperlessNgxConnector(
            api_url=api_url,
            # ingest_tags="INBOX, TODO",
            # ingest_tags="ai-process",
            ingest_usernames="cbrown",
            # ingest_noowner=True,
        )
        test_connector.load_credentials(
            {
                "paperless_ngx_auth_token": auth_token,
            }
        )

        print("\n--- Testing load_from_state ---")
        try:
            all_docs_iter = test_connector.load_from_state()
            all_docs = next(all_docs_iter, [])
            print(f"Total documents loaded: {len(all_docs)}")
            if all_docs:
                print(
                    f"First document sample: {all_docs[0].title} (ID: {all_docs[0].id})"
                )
        except Exception as e:
            print(f"Error during load_from_state: {e}", file=sys.stderr)

        print("\n--- Testing poll_source (documents from last 24 hours) ---")
        try:
            current = time.time()
            one_day_ago = current - (24 * 60 * 60)
            latest_docs_iter = test_connector.poll_source(one_day_ago, current)
            latest_docs = next(latest_docs_iter, [])
            print(f"Documents polled from last 24 hours: {len(latest_docs)}")
            if latest_docs:
                print(
                    f"First polled document sample: {latest_docs[0].title} (ID: {latest_docs[0].id})"
                )
        except Exception as e:
            print(f"Error during poll_source: {e}", file=sys.stderr)

        print("\n--- Testing retrieve_all_slim_documents ---")
        try:
            slim_docs_iter = test_connector.retrieve_all_slim_documents()
            slim_docs = next(slim_docs_iter, [])
            print(f"Total slim documents retrieved: {len(slim_docs)}")
            if slim_docs:
                print(f"First slim document sample ID: {slim_docs[0].id}")
        except Exception as e:
            print(f"Error during retrieve_all_slim_documents: {e}", file=sys.stderr)
