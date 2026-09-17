import io
import json
import mimetypes
from typing import IO, Any, List, Tuple, cast

import httpx

from onyx.file_store.models import FileDescriptor
from onyx.server.documents.models import FileUploadResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


class FileManager:
    @staticmethod
    def upload_files(
        files: List[Tuple[str, IO]],
        user_performing_action: DATestUser,
    ) -> Tuple[List[FileDescriptor], str]:
        headers = user_performing_action.headers
        headers.pop("Content-Type", None)

        files_param = []
        for filename, file_obj in files:
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type is None:
                mime_type = "application/octet-stream"
            files_param.append(("files", (filename, file_obj, mime_type)))

        response = client.post(
            f"{API_SERVER_URL}/user/projects/file/upload",
            files=files_param,
            headers=headers,
        )

        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            return (
                cast(List[FileDescriptor], []),
                f"Failed to upload files - {detail}",
            )

        response_json = response.json()
        # Convert UserFileSnapshot to FileDescriptor format
        file_descriptors: List[FileDescriptor] = [
            {
                "id": user_file["file_id"],
                "type": user_file["chat_file_type"],
                "name": user_file["name"],
                "user_file_id": str(user_file["id"]),
            }
            for user_file in response_json.get("user_files", [])
        ]
        return file_descriptors, ""

    @staticmethod
    def fetch_uploaded_file(
        file_id: str,
        user_performing_action: DATestUser,
    ) -> bytes:
        response = client.get(
            f"{API_SERVER_URL}/chat/file/{file_id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def upload_connector_files(
        files: List[Tuple[str, bytes]],
        user_performing_action: DATestUser,
        content_type: str = "application/octet-stream",
    ) -> httpx.Response:
        """Raw response, so a permission test can assert a denial instead of raising."""
        headers = user_performing_action.headers.copy()
        headers.pop("Content-Type", None)
        return client.post(
            f"{API_SERVER_URL}/manage/admin/connector/file/upload",
            files=[
                ("files", (file_name, io.BytesIO(content), content_type))
                for file_name, content in files
            ],
            headers=headers,
            cookies=user_performing_action.cookies,
        )

    @staticmethod
    def upload_connector_file(
        file_name: str,
        content: bytes,
        user_performing_action: DATestUser,
        content_type: str = "application/octet-stream",
    ) -> FileUploadResponse:
        response = FileManager.upload_connector_files(
            [(file_name, content)], user_performing_action, content_type
        )
        if response.is_error:
            try:
                error_detail = response.json().get("detail", "Unknown error")
            except Exception:
                error_detail = response.text

            raise Exception(
                f"Unable to upload files - {error_detail} (Status code: {response.status_code})"
            )

        return FileUploadResponse(**response.json())

    @staticmethod
    def upload_file_for_connector(
        file_path: str,
        file_name: str,
        user_performing_action: DATestUser,
        content_type: str = "application/octet-stream",
    ) -> FileUploadResponse:
        with open(file_path, "rb") as f:
            return FileManager.upload_connector_file(
                file_name, f.read(), user_performing_action, content_type
            )

    @staticmethod
    def list_connector_files(
        connector_id: int,
        user_performing_action: DATestUser,
    ) -> httpx.Response:
        return client.get(
            f"{API_SERVER_URL}/manage/admin/connector/{connector_id}/files",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )

    @staticmethod
    def update_connector_files(
        connector_id: int,
        user_performing_action: DATestUser,
        file_ids_to_remove: List[str] | None = None,
        files: List[Tuple[str, bytes]] | None = None,
        content_type: str = "application/octet-stream",
    ) -> httpx.Response:
        headers = user_performing_action.headers.copy()
        headers.pop("Content-Type", None)
        # file_ids_to_remove rides in `files` as a plain part: httpx falls back to
        # urlencoded when the file list is empty, and the route only reads multipart.
        parts: List[Tuple[str, Any]] = [
            ("file_ids_to_remove", (None, json.dumps(file_ids_to_remove or [])))
        ]
        parts.extend(
            ("files", (file_name, io.BytesIO(content), content_type))
            for file_name, content in (files or [])
        )
        return client.post(
            f"{API_SERVER_URL}/manage/admin/connector/{connector_id}/files/update",
            files=parts,
            headers=headers,
            cookies=user_performing_action.cookies,
        )
