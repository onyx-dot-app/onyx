from typing import Any
from uuid import uuid4

import requests

from onyx.server.documents.models import CredentialSnapshot
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestUser


class CredentialManager:
    @staticmethod
    def create(
        credential_json: dict[str, Any] | None = None,
        admin_public: bool = True,
        name: str | None = None,
        source: DocumentSource = DocumentSource.FILE,
        curator_public: bool = True,
        groups: list[int] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestCredential:
        name = f"{name}-credential" if name else f"test-credential-{uuid4()}"

        credential_request = {
            "name": name,
            "credential_json": credential_json or {},
            "admin_public": admin_public,
            "source": source,
            "curator_public": curator_public,
            "groups": groups or [],
        }

        response = requests.post(
            url=f"{API_SERVER_URL}/manage/credential",
            json=credential_request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )

        response.raise_for_status()
        return DATestCredential(
            id=response.json()["id"],
            name=name,
            credential_json=credential_json or {},
            admin_public=admin_public,
            source=source,
            curator_public=curator_public,
            groups=groups or [],
        )

    @staticmethod
    def edit(
        credential: DATestCredential,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        request = credential.model_dump(include={"name", "credential_json"})
        response = requests.put(
            url=f"{API_SERVER_URL}/manage/admin/credential/{credential.id}",
            json=request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        credential: DATestCredential,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        response = requests.delete(
            url=f"{API_SERVER_URL}/manage/credential/{credential.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def get(
        credential_id: int, user_performing_action: DATestUser | None = None
    ) -> CredentialSnapshot:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/credential/{credential_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return CredentialSnapshot(**response.json())

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[CredentialSnapshot]:
        response = requests.get(
            f"{API_SERVER_URL}/manage/credential",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [CredentialSnapshot(**cred) for cred in response.json()]

    @staticmethod
    def verify(
        credential: DATestCredential,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        all_credentials = CredentialManager.get_all(user_performing_action)
        for fetched_credential in all_credentials:
            if credential.id == fetched_credential.id:
                if verify_deleted:
                    raise ValueError(
                        f"Credential {credential.id} found but should be deleted"
                    )
                if (
                    credential.name == fetched_credential.name
                    and credential.admin_public == fetched_credential.admin_public
                    and credential.source == fetched_credential.source
                    and credential.curator_public == fetched_credential.curator_public
                ):
                    return
        if not verify_deleted:
            raise ValueError(f"Credential {credential.id} not found")
