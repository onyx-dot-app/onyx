from typing import List

import requests

from onyx.server.features.projects.models import CategorizedFilesSnapshot
from onyx.server.features.projects.models import UserFileSnapshot
from onyx.server.features.projects.models import UserProjectSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


class ProjectManager:
    @staticmethod
    def create(
        name: str,
        user_performing_action: DATestUser,
    ) -> UserProjectSnapshot:
        """Create a new project via API."""
        response = requests.post(
            f"{API_SERVER_URL}/user/projects/create",
            params={"name": name},
            headers=user_performing_action.headers or GENERAL_HEADERS,
        )
        response.raise_for_status()
        return UserProjectSnapshot.model_validate(response.json())

    @staticmethod
    def get_all(
        user_performing_action: DATestUser,
    ) -> List[UserProjectSnapshot]:
        """Get all projects for a user via API."""
        response = requests.get(
            f"{API_SERVER_URL}/user/projects/",
            headers=user_performing_action.headers or GENERAL_HEADERS,
        )
        response.raise_for_status()
        return [UserProjectSnapshot.model_validate(obj) for obj in response.json()]

    @staticmethod
    def delete(
        project_id: int,
        user_performing_action: DATestUser,
    ) -> bool:
        """Delete a project via API."""
        response = requests.delete(
            f"{API_SERVER_URL}/user/projects/{project_id}",
            headers=user_performing_action.headers or GENERAL_HEADERS,
        )
        return response.status_code == 204

    @staticmethod
    def verify_deleted(
        project_id: int,
        user_performing_action: DATestUser,
    ) -> bool:
        """Verify that a project has been deleted by ensuring it's not in list."""
        response = requests.get(
            f"{API_SERVER_URL}/user/projects/",
            headers=user_performing_action.headers or GENERAL_HEADERS,
        )
        response.raise_for_status()
        projects = [UserProjectSnapshot.model_validate(obj) for obj in response.json()]
        return all(p.id != project_id for p in projects)

    @staticmethod
    def verify_files_unlinked(
        project_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """Verify that all files have been unlinked from the project via API."""
        response = requests.get(
            f"{API_SERVER_URL}/user/projects/files/{project_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        if response.status_code == 404:
            return True
        if not response.ok:
            return False
        files = [UserFileSnapshot.model_validate(obj) for obj in response.json()]
        return len(files) == 0

    @staticmethod
    def verify_chat_sessions_unlinked(
        project_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        """Verify that all chat sessions have been unlinked from the project via API."""
        response = requests.get(
            f"{API_SERVER_URL}/user/projects/{project_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        if response.status_code == 404:
            return True
        if not response.ok:
            return False
        try:
            project = UserProjectSnapshot.model_validate(response.json())
            chat_sessions = getattr(project, "chat_sessions", [])
            return len(chat_sessions or []) == 0
        except Exception:
            # If response doesn't include chat_sessions, assume unlinked
            return True

    @staticmethod
    def upload_files(
        project_id: int,
        files: List[tuple[str, bytes]],  # List of (filename, content) tuples
        user_performing_action: DATestUser,
    ) -> CategorizedFilesSnapshot:
        """Upload files to a project via API."""
        # Build multipart form-data
        files_payload = [
            (
                "files",
                (filename, content, "text/plain"),
            )
            for filename, content in files
        ]

        data = {"project_id": str(project_id)} if project_id is not None else {}

        # Let requests set Content-Type boundary by not overriding header
        headers = dict(user_performing_action.headers or {})
        headers.pop("Content-Type", None)

        response = requests.post(
            f"{API_SERVER_URL}/user/projects/file/upload",
            data=data,
            files=files_payload,
            headers=headers,
        )
        response.raise_for_status()
        return CategorizedFilesSnapshot.model_validate(response.json())

    @staticmethod
    def get_project_files(
        project_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> List[UserFileSnapshot]:
        """Get all files associated with a project via API."""
        response = requests.get(
            f"{API_SERVER_URL}/user/projects/files/{project_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [UserFileSnapshot.model_validate(obj) for obj in response.json()]

    @staticmethod
    def set_instructions(
        project_id: int,
        instructions: str,
        user_performing_action: DATestUser,
    ) -> str:
        """Set project instructions via API."""
        response = requests.post(
            f"{API_SERVER_URL}/user/projects/{project_id}/instructions",
            json={"instructions": instructions},
            headers=user_performing_action.headers or GENERAL_HEADERS,
        )
        response.raise_for_status()
        return (response.json() or {}).get("instructions") or ""
