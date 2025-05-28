import time
from uuid import uuid4

import requests

from ee.onyx.server.user_group.models import UserGroup
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup


class UserGroupManager:
    @staticmethod
    def create(
        name: str | None = None,
        user_ids: list[str] | None = None,
        cc_pair_ids: list[int] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestUserGroup:
        name = f"{name}-user-group" if name else f"test-user-group-{uuid4()}"

        request = {
            "name": name,
            "user_ids": user_ids or [],
            "cc_pair_ids": cc_pair_ids or [],
        }
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/user-group",
            json=request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        test_user_group = DATestUserGroup(
            id=response.json()["id"],
            name=response.json()["name"],
            user_ids=[user["id"] for user in response.json()["users"]],
            cc_pair_ids=[cc_pair["id"] for cc_pair in response.json()["cc_pairs"]],
        )
        return test_user_group

    @staticmethod
    def edit(
        user_group: DATestUserGroup,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        response = requests.patch(
            f"{API_SERVER_URL}/manage/admin/user-group/{user_group.id}",
            json=user_group.model_dump(),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        user_group: DATestUserGroup,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        response = requests.delete(
            f"{API_SERVER_URL}/manage/admin/user-group/{user_group.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def set_curator_status(
        test_user_group: DATestUserGroup,
        user_to_set_as_curator: DATestUser,
        is_curator: bool = True,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        set_curator_request = {
            "user_id": user_to_set_as_curator.id,
            "is_curator": is_curator,
        }
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/user-group/{test_user_group.id}/set-curator",
            json=set_curator_request,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[UserGroup]:
        response = requests.get(
            f"{API_SERVER_URL}/manage/admin/user-group",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [UserGroup(**ug) for ug in response.json()]

    @staticmethod
    def verify(
        user_group: DATestUserGroup,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        all_user_groups = UserGroupManager.get_all(user_performing_action)
        for fetched_user_group in all_user_groups:
            if user_group.id == fetched_user_group.id:
                if verify_deleted:
                    raise ValueError(
                        f"User group {user_group.id} found but should be deleted"
                    )
                fetched_cc_ids = {cc_pair.id for cc_pair in fetched_user_group.cc_pairs}
                fetched_user_ids = {user.id for user in fetched_user_group.users}
                user_group_cc_ids = set(user_group.cc_pair_ids)
                user_group_user_ids = set(user_group.user_ids)
                if (
                    fetched_cc_ids == user_group_cc_ids
                    and fetched_user_ids == user_group_user_ids
                ):
                    return
        if not verify_deleted:
            raise ValueError(f"User group {user_group.id} not found")

    @staticmethod
    def wait_for_sync(
        user_groups_to_check: list[DATestUserGroup] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        start = time.time()
        while True:
            user_groups = UserGroupManager.get_all(user_performing_action)
            if user_groups_to_check:
                check_ids = {user_group.id for user_group in user_groups_to_check}
                user_group_ids = {user_group.id for user_group in user_groups}
                if not check_ids.issubset(user_group_ids):
                    raise RuntimeError("User group not found")
                user_groups = [
                    user_group
                    for user_group in user_groups
                    if user_group.id in check_ids
                ]
            if all(ug.is_up_to_date for ug in user_groups):
                print("User groups synced successfully.")
                return

            if time.time() - start > MAX_DELAY:
                raise TimeoutError(
                    f"User groups were not synced within the {MAX_DELAY} seconds"
                )
            else:
                print("User groups were not synced yet, waiting...")
            time.sleep(2)

    @staticmethod
    def wait_for_deletion_completion(
        user_groups_to_check: list[DATestUserGroup],
        user_performing_action: DATestUser | None = None,
    ) -> None:
        start = time.time()
        user_group_ids_to_check = {user_group.id for user_group in user_groups_to_check}
        while True:
            fetched_user_groups = UserGroupManager.get_all(user_performing_action)
            fetched_user_group_ids = {
                user_group.id for user_group in fetched_user_groups
            }
            if not user_group_ids_to_check.intersection(fetched_user_group_ids):
                return

            if time.time() - start > MAX_DELAY:
                raise TimeoutError(
                    f"User groups deletion was not completed within the {MAX_DELAY} seconds"
                )
            else:
                print("Some user groups are still being deleted, waiting...")
            time.sleep(2)
