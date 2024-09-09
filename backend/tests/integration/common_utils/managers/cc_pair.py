import time
from typing import Any
from uuid import uuid4

import requests

from danswer.connectors.models import InputType
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.server.documents.models import ConnectorIndexingStatus
from danswer.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.test_models import TestCCPair
from tests.integration.common_utils.test_models import TestUser


def _cc_pair_creator(
    connector_id: int,
    credential_id: int,
    name: str | None = None,
    is_public: bool = True,
    groups: list[int] | None = None,
    user_performing_action: TestUser | None = None,
) -> TestCCPair:
    name = f"{name}-cc-pair" if name else f"test-cc-pair-{uuid4()}"

    request = {
        "name": name,
        "is_public": is_public,
        "groups": groups or [],
    }

    response = requests.put(
        url=f"{API_SERVER_URL}/manage/connector/{connector_id}/credential/{credential_id}",
        json=request,
        headers=user_performing_action.headers
        if user_performing_action
        else GENERAL_HEADERS,
    )
    response.raise_for_status()
    return TestCCPair(
        id=response.json()["data"],
        name=name,
        connector_id=connector_id,
        credential_id=credential_id,
        is_public=is_public,
        groups=groups or [],
    )


class CCPairManager:
    @staticmethod
    def create_from_scratch(
        name: str | None = None,
        is_public: bool = True,
        groups: list[int] | None = None,
        source: DocumentSource = DocumentSource.FILE,
        input_type: InputType = InputType.LOAD_STATE,
        connector_specific_config: dict[str, Any] | None = None,
        credential_json: dict[str, Any] | None = None,
        user_performing_action: TestUser | None = None,
    ) -> TestCCPair:
        connector = ConnectorManager.create(
            name=name,
            source=source,
            input_type=input_type,
            connector_specific_config=connector_specific_config,
            is_public=is_public,
            groups=groups,
            user_performing_action=user_performing_action,
        )
        credential = CredentialManager.create(
            credential_json=credential_json,
            name=name,
            source=source,
            curator_public=is_public,
            groups=groups,
            user_performing_action=user_performing_action,
        )
        return _cc_pair_creator(
            connector_id=connector.id,
            credential_id=credential.id,
            name=name,
            is_public=is_public,
            groups=groups,
            user_performing_action=user_performing_action,
        )

    @staticmethod
    def create(
        connector_id: int,
        credential_id: int,
        name: str | None = None,
        is_public: bool = True,
        groups: list[int] | None = None,
        user_performing_action: TestUser | None = None,
    ) -> TestCCPair:
        return _cc_pair_creator(
            connector_id=connector_id,
            credential_id=credential_id,
            name=name,
            is_public=is_public,
            groups=groups,
            user_performing_action=user_performing_action,
        )

    @staticmethod
    def pause_cc_pair(
        cc_pair: TestCCPair,
        user_performing_action: TestUser | None = None,
    ) -> None:
        result = requests.put(
            url=f"{API_SERVER_URL}/manage/admin/cc-pair/{cc_pair.id}/status",
            json={"status": "PAUSED"},
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        result.raise_for_status()

    @staticmethod
    def delete(
        cc_pair: TestCCPair,
        user_performing_action: TestUser | None = None,
    ) -> None:
        cc_pair_identifier = ConnectorCredentialPairIdentifier(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )
        result = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/deletion-attempt",
            json=cc_pair_identifier.model_dump(),
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        result.raise_for_status()

    @staticmethod
    def get_all(
        user_performing_action: TestUser | None = None,
    ) -> list[ConnectorIndexingStatus]:
        response = requests.get(
            f"{API_SERVER_URL}/manage/admin/connector/indexing-status",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()
        return [ConnectorIndexingStatus(**cc_pair) for cc_pair in response.json()]

    @staticmethod
    def verify(
        cc_pair: TestCCPair,
        verify_deleted: bool = False,
        user_performing_action: TestUser | None = None,
    ) -> None:
        all_cc_pairs = CCPairManager.get_all(user_performing_action)
        for retrieved_cc_pair in all_cc_pairs:
            if retrieved_cc_pair.cc_pair_id == cc_pair.id:
                if verify_deleted:
                    # We assume that this check will be performed after the deletion is
                    # already waited for
                    raise ValueError(
                        f"CC pair {cc_pair.id} found but should be deleted"
                    )
                if (
                    retrieved_cc_pair.name == cc_pair.name
                    and retrieved_cc_pair.connector.id == cc_pair.connector_id
                    and retrieved_cc_pair.credential.id == cc_pair.credential_id
                    and retrieved_cc_pair.public_doc == cc_pair.is_public
                    and set(retrieved_cc_pair.groups) == set(cc_pair.groups)
                ):
                    return

        if not verify_deleted:
            raise ValueError(f"CC pair {cc_pair.id} not found")

    @staticmethod
    def wait_for_deletion_completion(
        user_performing_action: TestUser | None = None,
    ) -> None:
        start = time.time()
        while True:
            cc_pairs = CCPairManager.get_all(user_performing_action)
            if all(
                cc_pair.cc_pair_status != ConnectorCredentialPairStatus.DELETING
                for cc_pair in cc_pairs
            ):
                return

            if time.time() - start > MAX_DELAY:
                raise TimeoutError(
                    f"CC pairs deletion was not completed within the {MAX_DELAY} seconds"
                )
            else:
                print("Some CC pairs are still being deleted, waiting...")
            time.sleep(2)
