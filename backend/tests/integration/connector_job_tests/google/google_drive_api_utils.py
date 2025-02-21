from typing import Any
from uuid import uuid4

from google.oauth2.service_account import Credentials

from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_google_docs_service
from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.google_utils.resources import GoogleDriveService


GOOGLE_SCOPES = {
    "google_drive": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/admin.directory.group",
        "https://www.googleapis.com/auth/admin.directory.user",
    ],
}


def _create_doc_service(drive_service: GoogleDriveService) -> GoogleDocsService:
    docs_service = get_google_docs_service(
        creds=drive_service._http.credentials,
        user_email=drive_service._http.credentials._subject,
    )
    return docs_service


class GoogleDriveManager:
    @staticmethod
    def create_impersonated_drive_service(
        service_account_key: dict, impersonated_user_email: str
    ) -> GoogleDriveService:
        """Gets a drive service that impersonates a specific user"""
        credentials = Credentials.from_service_account_info(
            service_account_key,
            scopes=GOOGLE_SCOPES["google_drive"],
            subject=impersonated_user_email,
        )

        service = get_drive_service(credentials, impersonated_user_email)

        # Verify impersonation
        about = service.about().get(fields="user").execute()
        if about.get("user", {}).get("emailAddress") != impersonated_user_email:
            raise ValueError(
                f"Failed to impersonate {impersonated_user_email}. "
                f"Instead got {about.get('user', {}).get('emailAddress')}"
            )
        return service

    @staticmethod
    def create_shared_drive(
        drive_service: GoogleDriveService, admin_email: str, test_id: str
    ) -> str:
        """
        Creates a shared drive and returns the drive's ID
        """
        try:
            about = drive_service.about().get(fields="user").execute()
            creating_user = about["user"]["emailAddress"]

            # Verify we're still impersonating the admin
            if creating_user != admin_email:
                raise ValueError(
                    f"Expected to create drive as {admin_email}, but instead created drive as {creating_user}"
                )

            drive_metadata = {"name": f"perm_sync_drive_{test_id}"}

            request_id = str(uuid4())
            drive = (
                drive_service.drives()
                .create(
                    body=drive_metadata,
                    requestId=request_id,
                    fields="id,name,capabilities",
                )
                .execute()
            )

            return drive["id"]
        except Exception as e:
            print(f"Error creating shared drive: {str(e)}")
            raise

    @staticmethod
    def create_empty_doc(
        drive_service: Any,
        drive_id: str,
    ) -> str:
        """
        Creates an empty document in the given drive and returns the document's ID
        """
        file_metadata = {
            "name": f"perm_sync_doc_{drive_id}_{str(uuid4())}",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [drive_id],
        }
        file = (
            drive_service.files()
            .create(body=file_metadata, supportsAllDrives=True)
            .execute()
        )

        return file["id"]

    @staticmethod
    def append_text_to_doc(
        drive_service: GoogleDriveService, doc_id: str, text: str
    ) -> None:
        docs_service = _create_doc_service(drive_service)

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [{"insertText": {"location": {"index": 1}, "text": text}}]
            },
        ).execute()

    @staticmethod
    def update_file_permissions(
        drive_service: Any, file_id: str, email: str, role: str = "reader"
    ) -> None:
        permission = {"type": "user", "role": role, "emailAddress": email}
        drive_service.permissions().create(
            fileId=file_id,
            body=permission,
            supportsAllDrives=True,
            sendNotificationEmail=False,
        ).execute()

    @staticmethod
    def remove_file_permissions(drive_service: Any, file_id: str, email: str) -> None:
        permissions = (
            drive_service.permissions()
            .list(fileId=file_id, supportsAllDrives=True)
            .execute()
        )
        # TODO: This is a hacky way to remove permissions. Removes anyone with reader role.
        # Need to find a way to map a user's email to a permission id.
        # The permissions.get returns a permissionID but email field is None,
        # something to do with it being a group or domain wide delegation.
        for permission in permissions.get("permissions", []):
            if permission.get("role") == "reader":
                drive_service.permissions().delete(
                    fileId=file_id,
                    permissionId=permission["id"],
                    supportsAllDrives=True,
                ).execute()
                break

    @staticmethod
    def make_file_public(drive_service: Any, file_id: str) -> None:
        permission = {"type": "anyone", "role": "reader"}
        drive_service.permissions().create(
            fileId=file_id, body=permission, supportsAllDrives=True
        ).execute()

    @staticmethod
    def cleanup_drive(drive_service: Any, drive_id: str) -> None:
        try:
            # Delete up to 2 files that match our pattern
            file_name_prefix = f"perm_sync_doc_{drive_id}"
            files = (
                drive_service.files()
                .list(
                    q=f"name contains '{file_name_prefix}'",
                    driveId=drive_id,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    corpora="drive",
                    fields="files(id)",
                )
                .execute()
            )

            for file in files.get("files", []):
                drive_service.files().delete(
                    fileId=file["id"], supportsAllDrives=True
                ).execute()

            # Then delete the drive
            drive_service.drives().delete(driveId=drive_id).execute()
        except Exception as e:
            print(f"Error cleaning up drive {drive_id}: {e}")
