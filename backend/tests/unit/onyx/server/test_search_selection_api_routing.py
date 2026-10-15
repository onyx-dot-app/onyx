import json
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ee.onyx.search import process_search_query
from ee.onyx.server.query_and_chat import search_backend
from ee.onyx.server.query_and_chat.models import (
    SearchFlowClassificationRequest,
    SendSearchQueryRequest,
)
from ee.onyx.server.query_and_chat.streaming_models import SearchQueriesPacket
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.search import api
from onyx.server.features.search.models import SearchRequest
from onyx.tools.constants import SEARCH_TOOL_ID


@contextmanager
def public_search_dependencies(primary: MagicMock) -> Iterator[MagicMock]:
    tool = MagicMock()
    tool.search.return_value.text = json.dumps({"results": []})
    with (
        patch.multiple(
            api,
            get_default_llm=MagicMock(return_value=primary),
            llm_from_provider=MagicMock(return_value=primary),
            get_current_search_settings=MagicMock(),
            get_default_document_index=MagicMock(),
            get_tools=MagicMock(
                return_value=[MagicMock(id=7, in_code_tool_id=SEARCH_TOOL_ID)]
            ),
            fetch_existing_llm_provider=MagicMock(),
            fetch_user_group_ids=MagicMock(return_value=[]),
            can_user_access_llm_provider=MagicMock(return_value=True),
            has_global_permission=MagicMock(return_value=False),
            LLMProviderView=MagicMock(),
            load_settings=MagicMock(
                return_value=MagicMock(auto_detect_search_filters=False)
            ),
        ),
        patch.object(api, "SearchTool", return_value=tool) as constructor,
    ):
        yield constructor


@pytest.mark.parametrize("configured", [False, True])
def test_public_search_keeps_rewrites_primary_and_resolves_selection_lazily(
    configured: bool,
) -> None:
    primary, selection = MagicMock(), MagicMock()
    primary.config.api_key = "primary-key"
    selection.config.api_key = "selection-key"
    with (
        public_search_dependencies(primary) as constructor,
        patch.object(
            api,
            "get_search_selection_llm",
            return_value=selection if configured else primary,
        ) as resolver,
        patch.object(api, "check_llm_cost_limit_for_provider") as cost,
    ):
        result = api.search(SearchRequest(query="runbook"), MagicMock(), MagicMock())
        assert result.results == []
        assert constructor.call_args.kwargs["llm"] is primary
        resolver.assert_not_called()
        assert [
            call.kwargs["llm_provider_api_key"] for call in cost.call_args_list
        ] == ["primary-key"]
        factory = constructor.call_args.kwargs["selection_llm_factory"]
        assert factory() is (selection if configured else primary)
        resolver.assert_called_once_with(fallback=primary)
        assert [
            call.kwargs["llm_provider_api_key"] for call in cost.call_args_list
        ] == ["primary-key"]


def test_public_search_explicit_model_bypasses_selection_default() -> None:
    primary = MagicMock()
    primary.config.api_key = "explicit-key"
    with (
        public_search_dependencies(primary) as constructor,
        patch.object(api, "get_search_selection_llm") as resolver,
        patch.object(api, "check_llm_cost_limit_for_provider") as cost,
    ):
        api.search(
            SearchRequest(query="runbook", provider="custom", model="chosen"),
            MagicMock(),
            MagicMock(),
        )
        assert constructor.call_args.kwargs["llm"] is primary
        assert constructor.call_args.kwargs.get("selection_llm_factory") is None
        resolver.assert_not_called()
        assert [
            call.kwargs["llm_provider_api_key"] for call in cost.call_args_list
        ] == ["explicit-key"]


def test_public_search_defers_unused_primary_provider_check_to_tool() -> None:
    primary, selection = MagicMock(), MagicMock()
    with (
        public_search_dependencies(primary) as constructor,
        patch.object(api, "get_search_selection_llm", return_value=selection),
        patch.object(api, "check_llm_cost_limit_for_provider") as cost,
    ):
        api.search(
            SearchRequest(query="runbook", skip_query_expansion=True),
            MagicMock(),
            MagicMock(),
        )
        assert constructor.call_args.kwargs["primary_llm_cost_checked"] is False
        assert constructor.call_args.kwargs["selection_llm_factory"]() is selection
        cost.assert_not_called()


@pytest.mark.parametrize("configured", [False, True])
def test_ee_search_expansion_uses_primary_and_selection_uses_its_own_default(
    configured: bool,
) -> None:
    primary, selection = MagicMock(), MagicMock()
    section = MagicMock()
    section.center_chunk.document_id = "doc-1"
    with (
        patch.multiple(
            process_search_query,
            get_default_llm=MagicMock(return_value=primary),
            get_current_search_settings=MagicMock(),
            get_default_document_index=MagicMock(),
            _run_single_search=MagicMock(return_value=[]),
            merge_individual_chunks=MagicMock(return_value=[section]),
        ),
        patch.object(
            process_search_query,
            "get_search_selection_llm",
            return_value=selection if configured else primary,
        ) as resolver,
        patch.object(
            process_search_query, "expand_keywords", return_value=[]
        ) as rewrite,
        patch.object(
            process_search_query,
            "select_sections_for_expansion",
            return_value=([section], None),
        ) as select,
        patch.object(
            process_search_query.SearchDocWithContent,
            "from_inference_sections",
            return_value=[],
        ),
    ):
        response = process_search_query.gather_search_stream(
            process_search_query.stream_search_query(
                SendSearchQueryRequest(
                    search_query="runbook",
                    run_query_expansion=True,
                    num_docs_fed_to_llm_selection=2,
                ),
                MagicMock(is_anonymous=True),
                MagicMock(),
            )
        )
    assert response.llm_selected_doc_ids == ["doc-1"]
    assert rewrite.call_args.kwargs["llm"] is primary
    assert rewrite.call_args.kwargs.get("enforce_llm_input_budget", False) is False
    assert select.call_args.kwargs["llm"] is (selection if configured else primary)
    assert select.call_args.kwargs["enforce_llm_input_budget"] is configured
    resolver.assert_called_once_with(fallback=primary)


@pytest.mark.parametrize("has_results", [False, True])
@pytest.mark.parametrize("run_query_expansion", [False, True])
@pytest.mark.parametrize("configured", [False, True])
def test_ee_endpoint_checks_selection_provider_only_when_selection_runs(
    has_results: bool,
    run_query_expansion: bool,
    configured: bool,
) -> None:
    primary, selection = MagicMock(), MagicMock()
    primary.config.api_key = "primary-key"
    selection.config.api_key = "selection-key"
    section = MagicMock()
    section.center_chunk.document_id = "doc-1"
    with (
        patch.object(search_backend, "get_default_llm", return_value=primary),
        patch.object(
            search_backend,
            "get_search_selection_llm",
            return_value=selection if configured else primary,
        ) as resolver,
        patch.object(search_backend, "check_token_rate_limits") as quota,
        patch.object(search_backend, "check_llm_cost_limit_for_provider") as cost,
        patch.multiple(
            process_search_query,
            get_current_search_settings=MagicMock(),
            get_default_document_index=MagicMock(),
            _run_single_search=MagicMock(return_value=[]),
            expand_keywords=MagicMock(return_value=[]),
            merge_individual_chunks=MagicMock(
                return_value=[section] if has_results else []
            ),
            select_sections_for_expansion=MagicMock(return_value=([section], None)),
        ),
        patch.object(
            process_search_query.SearchDocWithContent,
            "from_inference_sections",
            return_value=[],
        ),
    ):
        search_backend.handle_send_search_message(
            SendSearchQueryRequest(
                search_query="runbook",
                num_docs_fed_to_llm_selection=2,
                run_query_expansion=run_query_expansion,
            ),
            MagicMock(is_anonymous=True),
            MagicMock(),
        )
        quota.assert_called_once()
        if has_results:
            resolver.assert_called_once_with(fallback=primary)
        else:
            resolver.assert_not_called()
        expected_keys = ["primary-key"] if run_query_expansion else []
        if has_results and not configured and not run_query_expansion:
            expected_keys.append("primary-key")
        assert [
            call.kwargs["llm_provider_api_key"] for call in cost.call_args_list
        ] == expected_keys


def test_ee_no_llm_operations_resolve_no_models_or_provider_budgets() -> None:
    with (
        patch.object(search_backend, "get_default_llm") as primary,
        patch.object(search_backend, "get_search_selection_llm") as selection,
        patch.object(search_backend, "check_token_rate_limits") as quota,
        patch.object(search_backend, "check_llm_cost_limit_for_provider") as cost,
        patch.object(search_backend, "stream_search_query", return_value=iter([])),
        patch.object(search_backend, "gather_search_stream"),
    ):
        search_backend.handle_send_search_message(
            SendSearchQueryRequest(search_query="runbook"), MagicMock(), MagicMock()
        )
    primary.assert_not_called()
    selection.assert_not_called()
    quota.assert_not_called()
    cost.assert_not_called()


def test_ee_pipeline_with_no_llm_work_resolves_no_clients() -> None:
    with (
        patch.multiple(
            process_search_query,
            get_current_search_settings=MagicMock(),
            get_default_document_index=MagicMock(),
            _run_single_search=MagicMock(return_value=[]),
            merge_individual_chunks=MagicMock(return_value=[]),
        ),
        patch.object(process_search_query, "get_default_llm") as primary,
        patch.object(process_search_query, "get_search_selection_llm") as selection,
    ):
        response = process_search_query.gather_search_stream(
            process_search_query.stream_search_query(
                SendSearchQueryRequest(search_query="runbook"),
                MagicMock(is_anonymous=True),
                MagicMock(),
            )
        )
    assert response.all_executed_queries == ["runbook"]
    primary.assert_not_called()
    selection.assert_not_called()


def test_ee_flow_classification_uses_primary_not_background_or_selection() -> None:
    primary = MagicMock()
    primary.config.api_key = "primary-key"
    with (
        patch.object(search_backend, "get_default_llm", return_value=primary),
        patch.object(search_backend, "get_search_selection_llm") as selection,
        patch.object(search_backend, "check_llm_cost_limit_for_provider") as cost,
        patch.object(
            search_backend, "classify_is_search_flow", return_value=True
        ) as classify,
    ):
        result = search_backend.search_flow_classification(
            SearchFlowClassificationRequest(user_query="runbook"),
            MagicMock(),
            MagicMock(),
        )
    assert result.is_search_flow is True
    assert classify.call_args.kwargs["llm"] is primary
    assert classify.call_args.kwargs.get("enforce_llm_input_budget", False) is False
    assert cost.call_args.kwargs["llm_provider_api_key"] == "primary-key"
    selection.assert_not_called()


def test_ee_selection_provider_limit_still_returns_docs() -> None:
    error = OnyxError(OnyxErrorCode.RATE_LIMITED, "Provider budget exceeded")
    with (
        patch.multiple(
            process_search_query,
            get_current_search_settings=MagicMock(),
            get_default_document_index=MagicMock(),
            _run_single_search=MagicMock(return_value=[]),
            merge_individual_chunks=MagicMock(return_value=[MagicMock()]),
        ),
        patch.object(
            process_search_query.SearchDocWithContent,
            "from_inference_sections",
            return_value=[],
        ),
        patch.object(
            process_search_query, "select_sections_for_expansion"
        ) as selection,
    ):
        response = process_search_query.gather_search_stream(
            process_search_query.stream_search_query(
                SendSearchQueryRequest(
                    search_query="runbook", num_docs_fed_to_llm_selection=1
                ),
                MagicMock(is_anonymous=True),
                MagicMock(),
                primary_llm=MagicMock(),
                selection_llm_factory=MagicMock(side_effect=error),
            )
        )
    assert response.all_executed_queries == ["runbook"]
    assert response.llm_selected_doc_ids is None
    selection.assert_not_called()


def test_ee_stream_reports_lazy_selection_limit_as_error_packet() -> None:
    app = FastAPI()

    def packets(*_args: object, **_kwargs: object) -> Iterator[SearchQueriesPacket]:
        yield SearchQueriesPacket(all_executed_queries=["runbook"])
        raise OnyxError(OnyxErrorCode.RATE_LIMITED, "Provider budget exceeded")

    @app.get("/")
    def stream() -> object:
        return search_backend.handle_send_search_message(
            SendSearchQueryRequest(
                search_query="runbook", stream=True, num_docs_fed_to_llm_selection=1
            ),
            MagicMock(),
            MagicMock(),
        )

    with (
        patch.object(search_backend, "get_default_llm"),
        patch.object(search_backend, "check_token_rate_limits"),
        patch.object(search_backend, "get_session_with_current_tenant"),
        patch.object(search_backend, "stream_search_query", side_effect=packets),
        TestClient(app) as client,
    ):
        response = client.get("/")

    assert response.status_code == 200
    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"type": "search_queries", "all_executed_queries": ["runbook"]},
        {"type": "search_error", "error": "Provider budget exceeded"},
    ]
