import time
from typing import Any
from uuid import UUID
from uuid import uuid4

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.test_models import DATestDocumentSet
from tests.integration.common_utils.test_models import DATestUser


class DocumentSetManager:
    @staticmethod
    def create(
        name: str | None = None,
        description: str | None = None,
        cc_pair_ids: list[int] | None = None,
        is_public: bool = True,
        users: list[str] | None = None,
        groups: list[int] | None = None,
        federated_connectors: list[dict[str, Any]] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestDocumentSet:
        if name is None:
            name = f"test_doc_set_{str(uuid4())}"

        doc_set_creation_request = {
            "name": name,
            "description": description or name,
            "cc_pair_ids": cc_pair_ids or [],
            "is_public": is_public,
            "users": [str(UUID(user_id)) for user_id in (users or [])],
            "groups": groups or [],
            "federated_connectors": federated_connectors or [],
        }

        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/document-set",
            json=doc_set_creation_request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

        return DATestDocumentSet(
            id=int(response.json()),
            name=name,
            description=description or name,
            cc_pair_ids=cc_pair_ids or [],
            is_public=is_public,
            is_up_to_date=True,
            users=users or [],
            groups=groups or [],
            federated_connectors=federated_connectors or [],
        )

    @staticmethod
    def edit(
        document_set: DATestDocumentSet,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        doc_set_update_request = {
            "id": document_set.id,
            "description": document_set.description,
            "cc_pair_ids": document_set.cc_pair_ids,
            "is_public": document_set.is_public,
            "users": [str(UUID(user_id)) for user_id in document_set.users],
            "groups": document_set.groups,
            "federated_connectors": document_set.federated_connectors,
        }
        response = requests.patch(
            f"{API_SERVER_URL}/manage/admin/document-set",
            json=doc_set_update_request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return True

    @staticmethod
    def delete(
        document_set: DATestDocumentSet,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        response = requests.delete(
            f"{API_SERVER_URL}/manage/admin/document-set/{document_set.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return True

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestDocumentSet]:
        response = requests.get(
            f"{API_SERVER_URL}/manage/document-set",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [
            DATestDocumentSet(
                id=doc_set["id"],
                name=doc_set["name"],
                description=doc_set["description"],
                cc_pair_ids=[cc_pair["id"] for cc_pair in doc_set["cc_pair_summaries"]],
                is_public=doc_set["is_public"],
                is_up_to_date=doc_set["is_up_to_date"],
                users=[str(user_id) for user_id in doc_set["users"]],
                groups=doc_set["groups"],
                federated_connectors=doc_set["federated_connector_summaries"],
            )
            for doc_set in response.json()
        ]

    @staticmethod
    def wait_for_sync(
        document_sets_to_check: list[DATestDocumentSet] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        # wait for document sets to be synced
        start = time.time()
        while True:
            doc_sets = DocumentSetManager.get_all(user_performing_action)
            if document_sets_to_check:
                check_ids = {doc_set.id for doc_set in document_sets_to_check}
                doc_set_ids = {doc_set.id for doc_set in doc_sets}
                if not check_ids.issubset(doc_set_ids):
                    raise RuntimeError("Document set not found")
                doc_sets = [doc_set for doc_set in doc_sets if doc_set.id in check_ids]
            all_up_to_date = all(doc_set.is_up_to_date for doc_set in doc_sets)

            if all_up_to_date:
                print("Document sets synced successfully.")
                break

            if time.time() - start > MAX_DELAY:
                not_synced_doc_sets = [
                    doc_set for doc_set in doc_sets if not doc_set.is_up_to_date
                ]
                raise TimeoutError(
                    f"Document sets were not synced within the {MAX_DELAY} seconds. "
                    f"Remaining unsynced document sets: {len(not_synced_doc_sets)}. "
                    f"IDs: {[doc_set.id for doc_set in not_synced_doc_sets]}"
                )
            else:
                not_synced_doc_sets = [
                    doc_set for doc_set in doc_sets if not doc_set.is_up_to_date
                ]
                print(
                    f"Document sets were not synced yet, waiting... "
                    f"{len(not_synced_doc_sets)}/{len(doc_sets)} document sets still syncing. "
                    f"IDs: {[doc_set.id for doc_set in not_synced_doc_sets]}"
                )

            time.sleep(2)

    @staticmethod
    def verify(
        document_set: DATestDocumentSet,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        doc_sets = DocumentSetManager.get_all(user_performing_action)
        for doc_set in doc_sets:
            if doc_set.id == document_set.id:
                if verify_deleted:
                    raise ValueError(
                        f"Document set {document_set.id} found but should have been deleted"
                    )
                if (
                    doc_set.name == document_set.name
                    and set(doc_set.cc_pair_ids) == set(document_set.cc_pair_ids)
                    and doc_set.is_public == document_set.is_public
                    and set(doc_set.users) == set(document_set.users)
                    and set(doc_set.groups) == set(document_set.groups)
                    and doc_set.federated_connectors
                    == document_set.federated_connectors
                ):
                    return
        if not verify_deleted:
            raise ValueError(f"Document set {document_set.id} not found")
