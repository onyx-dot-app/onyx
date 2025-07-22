import time
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlencode

import requests

from onyx.background.indexing.models import IndexAttemptErrorPydantic
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexModelStatus
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexingStatus
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.models import IndexAttemptSnapshot
from onyx.server.documents.models import PaginatedReturn
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.test_models import DATestIndexAttempt
from tests.integration.common_utils.test_models import DATestUser


class IndexAttemptManager:
    @staticmethod
    def create_test_index_attempts(
        num_attempts: int,
        cc_pair_id: int,
        from_beginning: bool = False,
        status: IndexingStatus = IndexingStatus.SUCCESS,
        new_docs_indexed: int = 10,
        total_docs_indexed: int = 10,
        docs_removed_from_index: int = 0,
        error_msg: str | None = None,
        base_time: datetime | None = None,
    ) -> list[DATestIndexAttempt]:
        if base_time is None:
            base_time = datetime.now()

        attempts = []
        with get_session_with_current_tenant() as db_session:
            # Get the current search settings
            search_settings = get_current_search_settings(db_session)
            if (
                not search_settings
                or search_settings.status != IndexModelStatus.PRESENT
            ):
                raise ValueError("No current search settings found with PRESENT status")

            for i in range(num_attempts):
                time_created = base_time - timedelta(hours=i)

                index_attempt = IndexAttempt(
                    connector_credential_pair_id=cc_pair_id,
                    from_beginning=from_beginning,
                    status=status,
                    new_docs_indexed=new_docs_indexed,
                    total_docs_indexed=total_docs_indexed,
                    docs_removed_from_index=docs_removed_from_index,
                    error_msg=error_msg,
                    time_created=time_created,
                    time_started=time_created,
                    time_updated=time_created,
                    search_settings_id=search_settings.id,
                )

                db_session.add(index_attempt)
                db_session.flush()  # To get the ID

                attempts.append(
                    DATestIndexAttempt(
                        id=index_attempt.id,
                        status=index_attempt.status,
                        new_docs_indexed=index_attempt.new_docs_indexed,
                        total_docs_indexed=index_attempt.total_docs_indexed,
                        docs_removed_from_index=index_attempt.docs_removed_from_index,
                        error_msg=index_attempt.error_msg,
                        time_started=index_attempt.time_started,
                        time_updated=index_attempt.time_updated,
                    )
                )

            db_session.commit()

        return attempts

    @staticmethod
    def get_index_attempt_page(
        cc_pair_id: int,
        page: int = 0,
        page_size: int = 10,
        user_performing_action: DATestUser | None = None,
    ) -> PaginatedReturn[IndexAttemptSnapshot]:
        query_params: dict[str, str | int] = {
            "page_num": page,
            "page_size": page_size,
        }

        url = (
            f"{API_SERVER_URL}/manage/admin/cc-pair/{cc_pair_id}/index-attempts"
            f"?{urlencode(query_params, doseq=True)}"
        )
        response = requests.get(
            url=url,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        data = response.json()
        return PaginatedReturn(
            items=[IndexAttemptSnapshot(**item) for item in data["items"]],
            total_items=data["total_items"],
        )

    @staticmethod
    def get_latest_index_attempt_for_cc_pair(
        cc_pair_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> IndexAttemptSnapshot | None:
        """Get an IndexAttempt by ID"""
        index_attempts = IndexAttemptManager.get_index_attempt_page(
            cc_pair_id, user_performing_action=user_performing_action
        ).items
        if not index_attempts:
            return None

        index_attempts = sorted(
            index_attempts, key=lambda x: x.time_started or "0", reverse=True
        )
        return index_attempts[0]

    @staticmethod
    def wait_for_index_attempt_start(
        cc_pair_id: int,
        index_attempts_to_ignore: list[int] | None = None,
        timeout: float = MAX_DELAY,
        user_performing_action: DATestUser | None = None,
    ) -> IndexAttemptSnapshot:
        """Wait for an IndexAttempt to start"""
        start = datetime.now()
        index_attempts_to_ignore = index_attempts_to_ignore or []

        while True:
            index_attempt = IndexAttemptManager.get_latest_index_attempt_for_cc_pair(
                cc_pair_id=cc_pair_id,
                user_performing_action=user_performing_action,
            )
            if (
                index_attempt
                and index_attempt.time_started
                and index_attempt.id not in index_attempts_to_ignore
            ):
                return index_attempt

            elapsed = (datetime.now() - start).total_seconds()
            if elapsed > timeout:
                raise TimeoutError(
                    f"IndexAttempt for CC Pair {cc_pair_id} did not start within {timeout} seconds"
                )

    @staticmethod
    def get_index_attempt_by_id(
        index_attempt_id: int,
        cc_pair_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> IndexAttemptSnapshot:
        page_num = 0
        page_size = 10
        while True:
            page = IndexAttemptManager.get_index_attempt_page(
                cc_pair_id=cc_pair_id,
                page=page_num,
                page_size=page_size,
                user_performing_action=user_performing_action,
            )
            for attempt in page.items:
                if attempt.id == index_attempt_id:
                    return attempt

            if len(page.items) < page_size:
                break

            page_num += 1

        raise ValueError(f"IndexAttempt {index_attempt_id} not found")

    @staticmethod
    def wait_for_index_attempt_completion(
        index_attempt_id: int,
        cc_pair_id: int,
        timeout: float = MAX_DELAY,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        """Wait for an IndexAttempt to complete"""
        start = time.monotonic()
        while True:
            index_attempt = IndexAttemptManager.get_index_attempt_by_id(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair_id,
                user_performing_action=user_performing_action,
            )

            if index_attempt.status and index_attempt.status.is_terminal():
                print(
                    f"IndexAttempt {index_attempt_id} completed with status {index_attempt.status}"
                )
                return

            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"IndexAttempt {index_attempt_id} did not complete within {timeout} seconds"
                )

            print(
                f"Waiting for IndexAttempt {index_attempt_id} to complete. "
                f"elapsed={elapsed:.2f} timeout={timeout}"
            )
            time.sleep(5)

    @staticmethod
    def get_index_attempt_errors_for_cc_pair(
        cc_pair_id: int,
        include_resolved: bool = True,
        user_performing_action: DATestUser | None = None,
    ) -> list[IndexAttemptErrorPydantic]:
        url = f"{API_SERVER_URL}/manage/admin/cc-pair/{cc_pair_id}/errors?page_size=100"
        if include_resolved:
            url += "&include_resolved=true"
        response = requests.get(
            url=url,
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        data = response.json()
        return [IndexAttemptErrorPydantic(**item) for item in data["items"]]
