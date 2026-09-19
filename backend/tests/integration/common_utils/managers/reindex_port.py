import time
from typing import Any

import httpx

from onyx.configs.constants import DEFAULT_CC_PAIR_ID
from onyx.db.enums import ConnectorCredentialPairStatus, SwitchoverType
from onyx.db.port_attempt import ReindexErrorRow, ReindexProgressCounts
from tests.integration.common_utils.constants import API_SERVER_URL, MAX_DELAY
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
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
    def wont_port_cc_pair_ids(
        user_performing_action: DATestUser,
        switchover_type: str = SwitchoverType.REINDEX.value,
    ) -> list[int]:
        """The cc_pairs this reindex will not carry into the new index, i.e. the set the
        admin must consent to delete. Mirrors the server's compute_wont_port_cc_pair_ids
        (INVALID always, plus PAUSED under ACTIVE_ONLY; DELETING and the default Ingestion
        pair excluded) off the indexing-status API."""
        wont_port_statuses = {ConnectorCredentialPairStatus.INVALID}
        if switchover_type == SwitchoverType.ACTIVE_ONLY.value:
            wont_port_statuses.add(ConnectorCredentialPairStatus.PAUSED)
        return sorted(
            status.cc_pair_id
            for status in CCPairManager.get_indexing_statuses(user_performing_action)
            if status.cc_pair_id != DEFAULT_CC_PAIR_ID
            and status.cc_pair_status in wont_port_statuses
        )

    @staticmethod
    def start_reindex_response(
        user_performing_action: DATestUser,
        switchover_type: str = SwitchoverType.REINDEX.value,
        enable_contextual_rag: bool | None = None,
        contextual_rag_model_configuration_id: int | None = None,
        acknowledged_wont_port_cc_pair_ids: list[int] | None = None,
    ) -> httpx.Response:
        """Reindex to the current embedding model (a new ALT index), which forces the
        port flow to re-embed PRESENT->FUTURE. Returns the raw response so a caller can
        assert on a guard rejection; use `start_reindex` when it must succeed.
        `switchover_type` is a SwitchoverType value ("reindex" waits for the port before
        swapping; "instant" swaps immediately and backfills the live index after).

        The server refuses the reindex unless every cc_pair that won't be ported is
        acknowledged for deletion. Callers that don't care consent to whatever the
        connectors happen to be; pass an explicit list to drive the consent guard.

        Leaving `enable_contextual_rag` / `contextual_rag_model_configuration_id` unset
        preserves whatever the tenant already has, so a reindex that isn't testing
        contextual RAG can't silently disable it. Pass either explicitly to change it."""
        if acknowledged_wont_port_cc_pair_ids is None:
            acknowledged_wont_port_cc_pair_ids = (
                ReindexPortManager.wont_port_cc_pair_ids(
                    user_performing_action, switchover_type
                )
            )
        current = ReindexPortManager.get_current_settings(user_performing_action)
        if enable_contextual_rag is None:
            enable_contextual_rag = current.get("enable_contextual_rag", False)
        if contextual_rag_model_configuration_id is None:
            contextual_rag_model_configuration_id = current.get(
                "contextual_rag_model_configuration_id"
            )
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
            "acknowledged_wont_port_cc_pair_ids": acknowledged_wont_port_cc_pair_ids,
        }
        return client.post(
            f"{SEARCH_SETTINGS_URL}/set-new-search-settings",
            json=payload,
            headers=user_performing_action.headers,
        )

    @staticmethod
    def start_reindex(user_performing_action: DATestUser, **kwargs: Any) -> int:
        """Start a reindex that must be accepted. Returns the new FUTURE settings id."""
        response = ReindexPortManager.start_reindex_response(
            user_performing_action, **kwargs
        )
        response.raise_for_status()
        return int(response.json()["id"])

    @staticmethod
    def wait_for_reindex_accepted(
        user_performing_action: DATestUser,
        timeout: float = MAX_DELAY,
        **kwargs: Any,
    ) -> int:
        """Start a reindex, retrying while the name-reuse guard rejects it.

        A new FUTURE can want the index name an earlier generation still occupies. The
        server refuses with 409 and hands that occupant to the reclaim loop, telling the
        admin to start the re-index again in a moment -- this is that retry. Any other
        rejection raises immediately."""
        start = time.monotonic()
        while True:
            response = ReindexPortManager.start_reindex_response(
                user_performing_action, **kwargs
            )
            if response.status_code != 409:
                response.raise_for_status()
                return int(response.json()["id"])

            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Reindex was still refused after {timeout}s: {response.text}"
                )
            print(
                f"Waiting for the occupied index name to be reclaimed: {elapsed:.1f}s"
            )
            time.sleep(5)

    @staticmethod
    def cancel_reindex_response(
        user_performing_action: DATestUser,
    ) -> httpx.Response:
        """Revert the in-progress reindex, returning the raw response so a caller can
        assert on a rejection; use `cancel_reindex` when it must succeed."""
        return client.post(
            f"{SEARCH_SETTINGS_URL}/cancel-new-embedding",
            headers=user_performing_action.headers,
        )

    @staticmethod
    def cancel_reindex(user_performing_action: DATestUser) -> None:
        ReindexPortManager.cancel_reindex_response(
            user_performing_action
        ).raise_for_status()

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
