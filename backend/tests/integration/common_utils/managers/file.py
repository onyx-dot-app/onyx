import io
import mimetypes
from typing import cast
from typing import IO
from typing import List
from typing import Tuple

import requests

from onyx.file_store.models import FileDescriptor
from onyx.server.documents.models import FileUploadResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


class FileManager:
    @staticmethod
    def upload_files(
        files: List[Tuple[str, IO]],
        user_performing_action: DATestUser | None = None,
    ) -> Tuple[List[FileDescriptor], str]:
        headers = (
            user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS
        )
        headers.pop("Content-Type", None)

        files_param = []
        for filename, file_obj in files:
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type is None:
                mime_type = "application/octet-stream"
            files_param.append(("files", (filename, file_obj, mime_type)))

        response = requests.post(
            f"{API_SERVER_URL}/chat/file",
            files=files_param,
            headers=headers,
        )

        if not response.ok:
            return (
                cast(List[FileDescriptor], []),
                f"Failed to upload files - {response.json().get('detail', 'Unknown error')}",
            )

        response_json = response.json()
        return response_json.get("files", cast(List[FileDescriptor], [])), ""

    @staticmethod
    def fetch_uploaded_file(
        file_id: str,
        user_performing_action: DATestUser | None = None,
    ) -> bytes:
        response = requests.get(
            f"{API_SERVER_URL}/chat/file/{file_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def upload_file_for_connector(
        file_path: str,
        file_name: str,
        user_performing_action: DATestUser,
        content_type: str = "application/octet-stream",
    ) -> FileUploadResponse:
        # Read the file content
        with open(file_path, "rb") as f:
            file_content = f.read()

        # Create a file-like object
        file_obj = io.BytesIO(file_content)

        # The 'files' form field expects a list of files
        files = [("files", (file_name, file_obj, content_type))]

        # Use the user's headers but without Content-Type
        # as requests will set the correct multipart/form-data Content-Type for us
        headers = user_performing_action.headers.copy()
        if "Content-Type" in headers:
            del headers["Content-Type"]

        # Make the request
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/connector/file/upload",
            files=files,
            headers=headers,
        )

        if not response.ok:
            try:
                error_detail = response.json().get("detail", "Unknown error")
            except Exception:
                error_detail = response.text

            raise Exception(
                f"Unable to upload files - {error_detail} (Status code: {response.status_code})"
            )

        response_json = response.json()
        return FileUploadResponse(**response_json)
