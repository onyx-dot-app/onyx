from onyx.configs.app_configs import EXT_APP_GOOGLE_DRIVE_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_GOOGLE_DRIVE_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.google_base import GoogleOAuthProvider


# Google Drive API v3. Reads (GET) live under `/drive/v3/...`; content uploads
# use the separate `/upload/drive/v3/...` host path, so both prefixes appear in
# the upstream patterns and the catalog. The Google Docs API is a separate host
# (`docs.googleapis.com/v1/documents/...`) authorized by the same `auth/drive`
# scope. Reads default to ALWAYS; every mutation defaults to ASK so the egress
# approval gate prompts the user before it runs.
class GoogleDriveAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Google Drive provider."""

    FILES_READ = "gdrive.files.read"
    FILES_EXPORT = "gdrive.files.export"
    DRIVES_READ = "gdrive.drives.read"
    FILES_CREATE = "gdrive.files.create"
    FILES_UPDATE = "gdrive.files.update"
    FILES_DELETE = "gdrive.files.delete"
    DOCS_READ = "gdrive.docs.read"
    DOCS_CREATE = "gdrive.docs.create"
    DOCS_UPDATE = "gdrive.docs.update"


_FILES = "/drive/v3/files"
_FILE_ITEM = f"{_FILES}/{{fileId}}"
_UPLOAD_FILES = "/upload/drive/v3/files"
_UPLOAD_ITEM = f"{_UPLOAD_FILES}/{{fileId}}"
_DOCS = "/v1/documents"
_DOC_ITEM = f"{_DOCS}/{{documentId}}"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=GoogleDriveAction.FILES_READ,
        normalised_name="Read files",
        description=(
            "Search/list files and folders, read a file's metadata, and download "
            "a non-native file's contents."
        ),
        matches=(
            RestRoute(method="GET", path=_FILES),
            RestRoute(method="GET", path=_FILE_ITEM),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleDriveAction.FILES_EXPORT,
        normalised_name="Export a document",
        description=(
            "Export a Google-native doc (Docs/Sheets/Slides) to text, markdown, "
            "or CSV so its contents can be read."
        ),
        matches=(RestRoute(method="GET", path=f"{_FILE_ITEM}/export"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleDriveAction.DRIVES_READ,
        normalised_name="List shared drives",
        description="List the shared drives the user can access.",
        matches=(
            RestRoute(method="GET", path="/drive/v3/drives"),
            RestRoute(method="GET", path="/drive/v3/drives/{driveId}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleDriveAction.FILES_CREATE,
        normalised_name="Create or upload a file",
        description=(
            "Create a folder/file or upload new content (optionally converting "
            "to a Google-native Doc/Sheet/Slides)."
        ),
        matches=(
            RestRoute(method="POST", path=_FILES),
            RestRoute(method="POST", path=_UPLOAD_FILES),
        ),
    ),
    EndpointSpec(
        id=GoogleDriveAction.FILES_UPDATE,
        normalised_name="Edit a file",
        description="Update a file's metadata or replace its contents.",
        matches=(
            RestRoute(method="PATCH", path=_FILE_ITEM),
            RestRoute(method="PATCH", path=_UPLOAD_ITEM),
        ),
    ),
    EndpointSpec(
        id=GoogleDriveAction.FILES_DELETE,
        normalised_name="Delete a file",
        description="Trash or permanently delete a file.",
        matches=(RestRoute(method="DELETE", path=_FILE_ITEM),),
    ),
    EndpointSpec(
        id=GoogleDriveAction.DOCS_READ,
        normalised_name="Read a document",
        description=(
            "Read a Google Doc's structured contents (text, formatting, and "
            "layout) via the Docs API."
        ),
        matches=(RestRoute(method="GET", path=_DOC_ITEM),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleDriveAction.DOCS_CREATE,
        normalised_name="Create a document",
        description="Create a new, empty Google Doc via the Docs API.",
        matches=(RestRoute(method="POST", path=_DOCS),),
    ),
    EndpointSpec(
        id=GoogleDriveAction.DOCS_UPDATE,
        normalised_name="Edit a document",
        description="Apply edits to a Google Doc's contents via the Docs API.",
        matches=(RestRoute(method="POST", path=_DOC_ITEM),),
    ),
]


class GoogleDriveProvider(GoogleOAuthProvider, OnyxManagedExtApp):
    spec = GoogleOAuthProvider.build_spec(
        app_type=ExternalAppType.GOOGLE_DRIVE,
        app_name="Google Drive",
        # Full drive scope: read, search, create, edit, and delete any of the
        # user's files. Mutations are gated by per-action ASK approval.
        scope="https://www.googleapis.com/auth/drive",
        upstream_url_patterns=[
            "https://www\\.googleapis\\.com/drive/.*",
            # Content uploads use the separate /upload host path.
            "https://www\\.googleapis\\.com/upload/drive/.*",
            # The Docs API lives on its own host.
            "https://docs\\.googleapis\\.com/.*",
        ],
        description=(
            "Search, read, create, and edit files and Google Docs in your "
            "Google Drive inside Onyx Craft."
        ),
        google_api_name="Google Drive API and Google Docs API",
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_GOOGLE_DRIVE_CLIENT_ID,
        "client_secret": EXT_APP_GOOGLE_DRIVE_CLIENT_SECRET,
    }
