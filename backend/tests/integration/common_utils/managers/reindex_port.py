import time

from onyx.db.port_attempt import ReindexErrorRow, ReindexProgressCounts
from tests.integration.common_utils.constants import API_SERVER_URL, MAX_DELAY
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

SEARCH_SETTINGS_URL = f"{API_SERVER_URL}/search-settings"


class ReindexPortManager:
    """Drives the reindex *port* flow through the real API + worker fleet.

    set-new-search-settings creates a port-flow FUTURE (use_port_flow=True). beat's
    check_for_port then enqueues a port attempt per in-scope cc_pair onto the `port`
    queue, the docprocessing worker re-embeds PRESENT->FUTURE, and the beat-driven
    swap promotes FUTURE->PRESENT once every required port succeeds. These helpers
    trigger that flow and poll its HTTP surface (reindex-progress / current settings)
    to completion, mirroring IndexAttemptManager's wait_for_* shape.
    """

    @staticmethod
    def get_current_settings(user_performing_action: DATestUser) -> dict:
        response = client.get(
            f"{SEARCH_SETTINGS_URL}/get-current-search-settings",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def get_secondary_settings(user_performing_action: DATestUser) -> dict | None:
        response = client.get(
            f"{SEARCH_SETTINGS_URL}/get-secondary-search-settings",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def start_reindex(
        user_performing_action: DATestUser,
        switchover_type: str = "reindex",
        enable_contextual_rag: bool = False,
        contextual_rag_model_configuration_id: int | None = None,
    ) -> int:
        """Reindex to the current embedding model (a new ALT index), which forces the
        port flow to re-embed PRESENT->FUTURE. Returns the new FUTURE settings id.
        `switchover_type` is a SwitchoverType value ("reindex" waits for the port before
        swapping; "instant" swaps immediately and backfills the live index after)."""
        current = ReindexPortManager.get_current_settings(user_performing_action)
        payload = {
            "model_name": current["model_name"],
            "model_dim": current["model_dim"],
            "normalize": current["normalize"],
            "query_prefix": current.get("query_prefix") or "",
            "passage_prefix": current.get("passage_prefix") or "",
            "provider_type": current.get("provider_type"),
            "index_name": None,
            "multipass_indexing": current.get("multipass_indexing", False),
            "embedding_precision": current["embedding_precision"],
            "reduced_dimension": current.get("reduced_dimension"),
            "switchover_type": switchover_type,
            "enable_contextual_rag": enable_contextual_rag,
            "contextual_rag_model_configuration_id": contextual_rag_model_configuration_id,
        }
        response = client.post(
            f"{SEARCH_SETTINGS_URL}/set-new-search-settings",
            json=payload,
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return int(response.json()["id"])

    @staticmethod
    def cancel_reindex(user_performing_action: DATestUser) -> None:
        response = client.post(
            f"{SEARCH_SETTINGS_URL}/cancel-new-embedding",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def get_progress(user_performing_action: DATestUser) -> ReindexProgressCounts:
        response = client.get(
            f"{SEARCH_SETTINGS_URL}/reindex-progress",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return ReindexProgressCounts(**response.json())

    @staticmethod
    def get_errors(user_performing_action: DATestUser) -> list[ReindexErrorRow]:
        response = client.get(
            f"{SEARCH_SETTINGS_URL}/reindex-errors",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return [ReindexErrorRow(**row) for row in response.json()]

    @staticmethod
    def wait_for_reindex_completion(
        user_performing_action: DATestUser,
        timeout: float = MAX_DELAY,
    ) -> ReindexProgressCounts:
        """Poll /reindex-progress until every in-scope port unit is done.

        Returns when all units are `completed` (swap imminent) OR when the port target
        disappears (`total==0`) because the swap already promoted the FUTURE. Raises on
        a FAILED/PAUSED unit -- unexpected in a happy-path reindex -- surfacing
        /reindex-errors for diagnosis.
        """
        start = time.monotonic()
        while True:
            progress = ReindexPortManager.get_progress(user_performing_action)
            if progress.failed or progress.paused:
                errors = ReindexPortManager.get_errors(user_performing_action)
                raise AssertionError(
                    f"Reindex port has failed/paused units: {progress} errors={errors}"
                )
            # total==0 -> no active port target: the swap already promoted the FUTURE.
            all_done = (
                progress.total > 0
                and progress.completed == progress.total
                and progress.in_progress == 0
                and progress.waiting == 0
            )
            if progress.total == 0 or all_done:
                return progress

            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Reindex port did not complete within {timeout}s: {progress}"
                )
            print(f"Waiting for reindex port: {progress} elapsed={elapsed:.1f}s")
            time.sleep(5)

    @staticmethod
    def wait_for_swap(
        original_index_name: str,
        user_performing_action: DATestUser,
        timeout: float = MAX_DELAY,
    ) -> dict:
        """Poll get-current-search-settings until the promoted index becomes PRESENT --
        i.e. the current index_name differs from the pre-reindex one."""
        start = time.monotonic()
        while True:
            current = ReindexPortManager.get_current_settings(user_performing_action)
            if current["index_name"] != original_index_name:
                print(
                    f"Index swap complete: {original_index_name} -> "
                    f"{current['index_name']}"
                )
                return current

            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Index swap did not happen within {timeout}s "
                    f"(still {original_index_name})"
                )
            time.sleep(5)
