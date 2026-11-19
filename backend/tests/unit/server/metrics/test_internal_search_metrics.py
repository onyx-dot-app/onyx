from unittest.mock import patch

from onyx.server.metrics import internal_search
from onyx.server.metrics.internal_search import (
    QueryAdmission,
    SearchLane,
    UserMessageSize,
    observe_internal_search,
    observe_query_analyze,
    record_query_admission,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_records_admission_by_tenant_lane_and_outcome() -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
    try:
        with patch.object(internal_search, "_query_admissions") as counter:
            record_query_admission(
                SearchLane.USER_MESSAGE, QueryAdmission.TOO_MANY_TERMS
            )
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    counter.labels.assert_called_once_with(
        tenant_id="tenant_a", lane="user_message", admission="too_many_terms"
    )
    counter.labels.return_value.inc.assert_called_once_with()


def test_records_search_duration_by_message_size() -> None:
    with patch.object(internal_search, "_search_duration") as histogram:
        observe_internal_search(UserMessageSize.MEDIUM, 1.5)

    histogram.labels.assert_called_once_with(user_message_size="medium")
    histogram.labels.return_value.observe.assert_called_once_with(1.5)


def test_metric_errors_do_not_propagate() -> None:
    with (
        patch.object(internal_search, "_query_admissions") as counter,
        patch.object(internal_search, "_analyze_duration") as analyze,
        patch.object(internal_search, "_search_duration") as search,
    ):
        counter.labels.side_effect = RuntimeError("boom")
        analyze.observe.side_effect = RuntimeError("boom")
        search.labels.side_effect = RuntimeError("boom")

        record_query_admission(SearchLane.GENERATED, QueryAdmission.SHORT)
        observe_query_analyze(0.001)
        observe_internal_search(UserMessageSize.SHORT, 0.5)
