import copy
from typing import Any
from unittest import mock

import pytest
import requests
from requests import HTTPError

from onyx.connectors.confluence.onyx_confluence import (
    _DEFAULT_PAGINATION_LIMIT,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.interfaces import CredentialsProviderInterface


# Helper to create mock responses
def _create_mock_response(
    status_code: int,
    json_data: dict[str, Any] | None = None,
    url: str = "",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    if json_data is not None:
        response.json = mock.Mock(return_value=json_data)  # type: ignore
    if status_code >= 400:
        response.reason = "Mock Error"
    return response


# Helper to create HTTPError
def _create_http_error(
    status_code: int,
    json_data: dict[str, Any] | None = None,
    url: str = "",
) -> requests.Response:
    response = _create_mock_response(status_code, json_data, url)
    response.raise_for_status = mock.Mock(side_effect=HTTPError(response=response))  # type: ignore
    return response


@pytest.fixture
def mock_credentials_provider() -> mock.Mock:
    provider = mock.Mock(spec=CredentialsProviderInterface)
    provider.is_dynamic.return_value = False
    provider.get_credentials.return_value = {"confluence_access_token": "dummy_token"}
    provider.get_tenant_id.return_value = "test_tenant"
    provider.get_provider_key.return_value = "test_key"
    provider.__enter__ = mock.Mock(return_value=None)
    provider.__exit__ = mock.Mock(return_value=None)
    return provider


@pytest.fixture
def confluence_server_client(mock_credentials_provider: mock.Mock) -> OnyxConfluence:
    confluence = OnyxConfluence(
        is_cloud=False,
        url="http://fake-confluence.com",
        credentials_provider=mock_credentials_provider,
        timeout=10,
    )
    # Mock the internal client directly for controlling 'get'
    # We also mock the base URL used by the client internally for easier comparison
    mock_internal_client = mock.Mock()
    mock_internal_client.url = confluence._url
    confluence._confluence = mock_internal_client
    confluence._kwargs = (
        confluence.shared_base_kwargs
    )  # Ensure _kwargs is set for potential re-init
    return confluence


def test_cql_paginate_all_expansions_handles_internal_pagination_error(
    confluence_server_client: OnyxConfluence, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Tests that cql_paginate_all_expansions correctly handles HTTP 500 errors
    during the expansion pagination phase (_paginate_url internal logic),
    retrying with smaller limits down to 1. It simulates successes and failures
    at limit=1 and expects the final error to be raised.

    Specifically, this test:

    1. Calls the top level cql query and gets a response with 3 children.
    2. Calls the expansion for the first child and gets a response with 2 children across 2 pages.
    3. Tries to call the expansion for the second child, gets a 500 error, and retries
       down to the limit of 1.
    4. At limit=1, simulates the following sequence for page requests:
       - Page 1 (start=0): Success
       - Page 2 (start=1): Success
       - Page 3 (start=2): Failure (500)
       - Page 4 (start=3): Failure (500) <- This is the error that should be raised
    5. Calls the expansion for the third child and gets a response with 1 child.
    6. The overall call succeeds.
    """
    caplog.set_level("WARNING")  # To check logging messages

    # Use constants from the client instance, but note the test logic goes below MINIMUM
    _TEST_MINIMUM_LIMIT = 1  # The limit this test expects the retry to reach

    top_level_cql = "test_cql"
    top_level_expand = "child_items"
    base_top_level_path = (
        f"rest/api/content/search?cql={top_level_cql}&expand={top_level_expand}"
    )
    initial_top_level_path = f"{base_top_level_path}&limit={_DEFAULT_PAGINATION_LIMIT}"

    # --- Mock Responses ---
    top_level_raw_response = {
        "results": [
            {
                "id": 1,
                "child_items": {
                    "results": [],  # Populated by _traverse_and_update
                    "_links": {
                        "next": f"/rest/api/content/1/child?limit={_DEFAULT_PAGINATION_LIMIT}"
                    },
                    "size": 0,
                },
            },
            {
                "id": 2,
                "child_items": {
                    "results": [],
                    "_links": {
                        "next": f"/rest/api/content/2/child?limit={_DEFAULT_PAGINATION_LIMIT}"
                    },
                    "size": 0,
                },
            },
            {
                "id": 3,
                "child_items": {
                    "results": [],
                    "_links": {
                        "next": f"/rest/api/content/3/child?limit={_DEFAULT_PAGINATION_LIMIT}"
                    },
                    "size": 0,
                },
            },
        ],
        "_links": {},
        "size": 3,
    }
    top_level_response = _create_mock_response(
        200,
        top_level_raw_response,
        url=initial_top_level_path,
    )

    # Expansion 1 - Needs 2 pages
    exp1_page1_path = f"rest/api/content/1/child?limit={_DEFAULT_PAGINATION_LIMIT}"
    # Note: _paginate_url internally calculates start for the next page
    exp1_page2_path = (
        f"rest/api/content/1/child?start=1&limit={_DEFAULT_PAGINATION_LIMIT}"
    )
    exp1_page1_response = _create_mock_response(
        200,
        {
            "results": [{"child_id": 101}],
            "_links": {"next": f"/{exp1_page2_path}"},
            "size": 1,
        },
        url=exp1_page1_path,
    )
    exp1_page2_response = _create_mock_response(
        200,
        {"results": [{"child_id": 102}], "_links": {}, "size": 1},
        url=exp1_page2_path,
    )

    # Problematic Expansion 2 URLs and Errors during limit reduction
    exp2_base_path = "rest/api/content/2/child"
    exp2_reduction_errors = {}
    limit = _DEFAULT_PAGINATION_LIMIT
    while limit > _TEST_MINIMUM_LIMIT:  # Reduce all the way to 1 for the test
        path = f"{exp2_base_path}?limit={limit}"
        exp2_reduction_errors[path] = _create_http_error(500, url=path)
        new_limit = limit // 2
        limit = max(new_limit, _TEST_MINIMUM_LIMIT)  # Ensure it hits 1

    # Expansion 2 - Pagination at Limit = 1 (2 successes, 2 failures)
    exp2_limit1_page1_path = f"{exp2_base_path}?limit={_TEST_MINIMUM_LIMIT}&start=0"
    exp2_limit1_page2_path = f"{exp2_base_path}?limit={_TEST_MINIMUM_LIMIT}&start=1"
    exp2_limit1_page3_path = f"{exp2_base_path}?limit={_TEST_MINIMUM_LIMIT}&start=2"
    exp2_limit1_page4_path = (
        f"{exp2_base_path}?limit={_TEST_MINIMUM_LIMIT}&start=3"  # Final failing call
    )
    exp2_limit1_page5_path = (
        f"{exp2_base_path}?limit={_TEST_MINIMUM_LIMIT}&start=4"  # Returns nothing
    )

    exp2_limit1_page1_response = _create_mock_response(
        200,
        {
            "results": [{"child_id": 201}],
            "_links": {"next": f"/{exp2_limit1_page2_path}"},
            "size": 1,
        },
        url=exp2_limit1_page1_path,
    )
    exp2_limit1_page2_error = _create_http_error(500, url=exp2_limit1_page2_path)
    exp2_limit1_page3_response = _create_mock_response(
        200,
        {
            "results": [{"child_id": 203}],
            "_links": {"next": f"/{exp2_limit1_page4_path}"},
            "size": 1,
        },
        url=exp2_limit1_page3_path,
    )
    exp2_limit1_page4_error = _create_http_error(
        500, url=exp2_limit1_page4_path
    )  # This is the one we expect to bubble up
    exp2_limit1_page5_response = _create_mock_response(
        200, {"results": [], "_links": {}, "size": 0}, url=exp2_limit1_page5_path
    )

    # Expansion 3
    exp3_page1_path = f"rest/api/content/3/child?limit={_DEFAULT_PAGINATION_LIMIT}"
    exp3_page1_response = _create_mock_response(
        200,
        {"results": [{"child_id": 301}], "_links": {}, "size": 1},
        url=exp3_page1_path,
    )

    # --- Side Effect Logic ---
    mock_get_call_paths: list[str] = []
    call_counts: dict[str, int] = {}  # Track calls to specific failing paths

    def get_side_effect(
        path: str,
        params: dict[str, Any] | None = None,
        advanced_mode: bool = False,
    ) -> requests.Response:
        path = path.strip("/")
        mock_get_call_paths.append(path)
        call_counts[path] = call_counts.get(path, 0) + 1
        print(f"Mock GET received path: {path} (Call #{call_counts[path]})")

        # Top Level Call
        if path == initial_top_level_path:
            print(f"-> Returning top level response for {path}")
            return top_level_response

        # Expansion 1 - Page 1
        elif path == exp1_page1_path:
            print(f"-> Returning expansion 1 page 1 for {path}")
            return exp1_page1_response

        # Expansion 1 - Page 2
        elif path == exp1_page2_path:
            print(f"-> Returning expansion 1 page 2 for {path}")
            return exp1_page2_response

        # Expansion 2 - Limit Reduction Errors
        elif path in exp2_reduction_errors:
            print(f"-> Failure: Returning response which raises 500 error for {path}")
            return exp2_reduction_errors[path]

        # Expansion 2 - Limit=1 Page 1 (Success)
        elif path == exp2_limit1_page1_path:
            print(f"-> Success: Returning expansion 2 limit 1 page 1 for {path}")
            return exp2_limit1_page1_response

        # Expansion 2 - Limit=1 Page 2 (Failure)
        elif path == exp2_limit1_page2_path:
            print(f"-> Failure: Returning response which raises 500 error for {path}")
            return exp2_limit1_page2_error

        # Expansion 2 - Limit=1 Page 3 (Success)
        elif path == exp2_limit1_page3_path:
            print(f"-> Success: Returning expansion 2 limit 1 page 3 for {path}")
            return exp2_limit1_page3_response

        # Expansion 2 - Limit=1 Page 4 (Failure)
        elif path == exp2_limit1_page4_path:
            print(f"-> Failure: Returning response which raises 500 error for {path}")
            return exp2_limit1_page4_error

        elif path == exp2_limit1_page5_path:
            print(f"-> Returning expansion 2 limit 1 page 5 for {path}")
            return exp2_limit1_page5_response

        # Expansion 3 - Page 1
        elif path == exp3_page1_path:
            print(f"-> Returning expansion 3 page 1 for {path}")
            return exp3_page1_response

        # Fallback
        print(f"!!! Unexpected GET path in mock: {path}")
        raise RuntimeError(f"Unexpected GET path in mock: {path}")

    confluence_server_client._confluence.get.side_effect = get_side_effect

    # --- Execute ---
    # Consume the iterator to trigger the calls
    result = list(
        confluence_server_client.cql_paginate_all_expansions(
            cql=top_level_cql,
            expand=top_level_expand,
            limit=_DEFAULT_PAGINATION_LIMIT,
        )
    )

    # Verify log for the failures during expansion 2 pagination (page 2 + 4)
    assert f"Error in confluence call to /{exp2_limit1_page2_path}" in caplog.text
    assert f"Error in confluence call to /{exp2_limit1_page4_path}" in caplog.text

    # Verify sequence of calls to 'get'
    # 1. Top level
    assert mock_get_call_paths[0] == initial_top_level_path
    # 2. Expansion 1 (page 1)
    assert mock_get_call_paths[1] == exp1_page1_path
    # 3. Expansion 1 (page 2)
    assert mock_get_call_paths[2] == exp1_page2_path
    # 4. Expansion 2 (initial attempt)
    assert (
        mock_get_call_paths[3] == f"{exp2_base_path}?limit={_DEFAULT_PAGINATION_LIMIT}"
    )

    # 5+. Expansion 2 (retries due to 500s, down to limit=1)
    call_index = 4

    # 5+N. Expansion 2 (limit=1, page 1 success)
    assert mock_get_call_paths[call_index] == exp2_limit1_page1_path
    call_index += 1
    # 5+N+1. Expansion 2 (limit=1, page 2 success)
    assert mock_get_call_paths[call_index] == exp2_limit1_page2_path
    call_index += 1
    # 5+N+2. Expansion 2 (limit=1, page 3 failure)
    assert mock_get_call_paths[call_index] == exp2_limit1_page3_path
    call_index += 1

    # 5+N+3. Expansion 2 (limit=1, page 4 failure)
    assert mock_get_call_paths[call_index] == exp2_limit1_page4_path
    call_index += 1

    # 5+N+4. Expansion 2 (limit=1, page 5 success, no results)
    assert mock_get_call_paths[call_index] == exp2_limit1_page5_path
    call_index += 1

    # Ensure Expansion 3 is called, that we continue after the final error-raising call
    assert mock_get_call_paths[call_index] == exp3_page1_path
    call_index += 1

    # Ensure correct number of calls
    assert len(mock_get_call_paths) == call_index

    # Ensure the result is correct
    # NOTE: size does not get updated during _traverse_and_update
    final_results = copy.deepcopy(top_level_raw_response)
    final_results["results"][0]["child_items"]["results"] = [{"child_id": 101}, {"child_id": 102}]  # type: ignore
    final_results["results"][1]["child_items"]["results"] = [{"child_id": 201}, {"child_id": 203}]  # type: ignore
    final_results["results"][2]["child_items"]["results"] = [{"child_id": 301}]  # type: ignore
    assert result == final_results["results"]


def test_paginated_cql_retrieval_handles_pagination_error(
    confluence_server_client: OnyxConfluence, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Tests that paginated_cql_retrieval correctly handles HTTP 500 errors
    during pagination, retrying with smaller limits down to 1, skipping
    the problematic item, and continuing.

    NOTE: in this context, a "page" is a set of results NOT a confluence page.

    Specifically, this test:
    1. Makes an initial CQL call with a limit, gets page 1 successfully.
    2. Attempts to get page 2 (based on the 'next' link), receives a 500 error.
    3. The internal _paginate_url logic retries page 2 with limit=1.
    4. Simulates the following sequence for page 2 retries (limit=1):
       - Item 1 (start=original_start + 0): Success
       - Item 2 (start=original_start + 1): Failure (500) - This item is skipped.
       - Item 3 (start=original_start + 2): Success
       - Item 4 (start=original_start + 3): Success, no more results in this chunk.
    5. The function continues to the next page (page 3) successfully.
    6. Checks that the results from page 1, items 1 & 3 from page 2 (retry),
       and page 3 are all returned.
    7. Verifies the error log for the skipped item (item 2).
    """
    caplog.set_level("WARNING")

    test_cql = "type=page"
    encoded_cql = "type%3Dpage"  # URL encoded version
    test_limit = 4  # Smaller limit for easier testing of page boundaries
    _TEST_MINIMUM_LIMIT = 1

    base_path = f"rest/api/content/search?cql={encoded_cql}"  # Use encoded cql
    page1_path = f"{base_path}&limit={test_limit}"
    # Page 2 starts where page 1 left off (start=test_limit)
    page2_initial_path = f"{base_path}&limit={test_limit}&start={test_limit}"
    # Page 3 starts after the problematic page 2 is processed (start=test_limit * 2)
    page3_path = f"{base_path}&limit={test_limit}&start={test_limit * 2}"

    # --- Mock Responses ---
    # Page 1: Success (4 items)
    page1_response = _create_mock_response(
        200,
        {
            "results": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            "_links": {"next": f"/{page2_initial_path}"},
            "size": 4,
        },
        url=page1_path,
    )

    # Page 2: Initial attempt fails with 500
    page2_initial_error = _create_http_error(500, url=page2_initial_path)

    # Page 2: Retry attempts with limit=1
    page2_limit1_start_offset = test_limit  # Start index for page 2 items
    page2_limit1_item1_path = (
        f"{base_path}&limit={_TEST_MINIMUM_LIMIT}&start={page2_limit1_start_offset + 0}"
    )
    page2_limit1_item2_path = (
        f"{base_path}&limit={_TEST_MINIMUM_LIMIT}&start={page2_limit1_start_offset + 1}"
    )
    page2_limit1_item3_path = (
        f"{base_path}&limit={_TEST_MINIMUM_LIMIT}&start={page2_limit1_start_offset + 2}"
    )
    page2_limit1_item4_path = (
        f"{base_path}&limit={_TEST_MINIMUM_LIMIT}&start={page2_limit1_start_offset + 3}"
    )

    page2_limit1_item1_response = _create_mock_response(
        200,
        {
            "results": [{"id": 5}],
            "_links": {"next": f"/{page2_limit1_item2_path}"},
            "size": 1,
        },  # Note: next link might be present but we check results
        url=page2_limit1_item1_path,
    )
    page2_limit1_item2_error = _create_http_error(
        500, url=page2_limit1_item2_path
    )  # The failure
    page2_limit1_item3_response = _create_mock_response(
        200,
        {
            "results": [{"id": 7}],
            "_links": {"next": f"/{page2_limit1_item4_path}"},
            "size": 1,
        },
        url=page2_limit1_item3_path,
    )
    page2_limit1_item4_response = _create_mock_response(
        200,
        {
            "results": [{"id": 8}],
            "_links": {"next": f"/{page3_path}"},
            "size": 1,
        },
        url=page2_limit1_item4_path,
    )

    # Page 3: Success (2 items)
    page3_response = _create_mock_response(
        200,
        {"results": [{"id": 9}, {"id": 10}], "_links": {}, "size": 2},  # No more pages
        url=page3_path,
    )

    # --- Side Effect Logic ---
    mock_get_call_paths: list[str] = []
    call_counts: dict[str, int] = {}  # Track calls

    def get_side_effect(
        path: str,
        params: dict[str, Any] | None = None,
        advanced_mode: bool = False,
    ) -> requests.Response:
        path = path.strip("/")
        mock_get_call_paths.append(path)
        call_counts[path] = call_counts.get(path, 0) + 1
        print(f"Mock GET received path: {path} (Call #{call_counts[path]})")

        # Page 1
        if path == page1_path:
            print(f"-> Returning page 1 success for {path}")
            return page1_response
        # Page 2 - Initial Failure
        elif path == page2_initial_path:
            print(f"-> Returning page 2 initial 500 error for {path}")
            return page2_initial_error
        # Page 2 - Limit 1 Retries
        elif path == page2_limit1_item1_path:
            print(f"-> Returning page 2 retry item 1 success for {path}")
            return page2_limit1_item1_response
        elif path == page2_limit1_item2_path:
            print(f"-> Returning page 2 retry item 2 500 error for {path}")
            return page2_limit1_item2_error
        elif path == page2_limit1_item3_path:
            print(f"-> Returning page 2 retry item 3 success for {path}")
            return page2_limit1_item3_response
        elif path == page2_limit1_item4_path:
            print(f"-> Returning page 2 retry item 4 success for {path}")
            return page2_limit1_item4_response
        # Page 3
        elif path == page3_path:
            print(f"-> Returning page 3 success for {path}")
            return page3_response
        # Fallback
        else:
            print(f"!!! Unexpected GET path in mock: {path}")
            raise RuntimeError(f"Unexpected GET path in mock: {path}")

    confluence_server_client._confluence.get.side_effect = get_side_effect

    # --- Execute ---
    results = list(
        confluence_server_client.paginated_cql_retrieval(
            cql=test_cql,
            limit=test_limit,
        )
    )

    # --- Assertions ---
    # Verify expected results (ids 1-4 from page 1, 5, 7, 8 from page 2 retry, 9-10 from page 3)
    expected_results = [
        # Page 1
        {"id": 1},
        {"id": 2},
        {"id": 3},
        {"id": 4},
        # Page 2, Item 1 (retry)
        {"id": 5},
        # {"id": 6}, # Skipped due to error
        {"id": 7},  # Page 2, Item 3 (retry)
        {"id": 8},  # Page 2, Item 4 (retry)
        # Page 3
        {"id": 9},
        {"id": 10},
    ]
    assert results == expected_results

    # Verify log for the skipped item failure
    assert f"Error in confluence call to /{page2_limit1_item2_path}" in caplog.text

    # Verify sequence of calls
    expected_calls = [
        page1_path,  # Page 1 success
        page2_initial_path,  # Page 2 initial fail (500)
        # _paginate_url internal retry logic starts here
        page2_limit1_item1_path,  # Page 2 retry item 1 success
        page2_limit1_item2_path,  # Page 2 retry item 2 fail (500) -> logged & skipped
        page2_limit1_item3_path,  # Page 2 retry item 3 success
        page2_limit1_item4_path,  # Page 2 retry item 4 success
        # _paginate_url continues to next calculated page (page 3)
        page3_path,  # Page 3 success
    ]
    assert mock_get_call_paths == expected_calls


def test_paginated_cql_retrieval_skips_completely_failing_page(
    confluence_server_client: OnyxConfluence, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Tests that paginated_cql_retrieval skips an entire page if the initial
    fetch fails and all subsequent limit=1 retries also fail. It should
    then proceed to fetch the next page successfully.
    """
    caplog.set_level("WARNING")

    test_cql = "type=page"
    encoded_cql = "type%3Dpage"
    test_limit = 3  # Small limit for testing
    _TEST_MINIMUM_LIMIT = 1

    base_path = f"rest/api/content/search?cql={encoded_cql}"
    page1_path = f"{base_path}&limit={test_limit}"
    # Page 2 starts where page 1 left off (start=test_limit)
    page2_initial_path = f"{base_path}&limit={test_limit}&start={test_limit}"
    # Page 3 starts after the completely failed page 2 (start=test_limit * 2)
    page3_path = f"{base_path}&limit={test_limit}&start={test_limit * 2}"

    # --- Mock Responses ---
    # Page 1: Success (3 items)
    page1_response = _create_mock_response(
        200,
        {
            "results": [{"id": 1}, {"id": 2}, {"id": 3}],
            "_links": {"next": f"/{page2_initial_path}"},
            "size": 3,
        },
        url=page1_path,
    )

    # Page 2: Initial attempt fails with 500
    page2_initial_error = _create_http_error(500, url=page2_initial_path)

    # Page 2: Retry attempts with limit=1 (ALL fail)
    page2_limit1_start_offset = test_limit
    page2_limit1_retry_errors = {}
    # Generate failing responses for each item expected on page 2
    for i in range(test_limit):
        item_path = f"{base_path}&limit={_TEST_MINIMUM_LIMIT}&start={page2_limit1_start_offset + i}"
        page2_limit1_retry_errors[item_path] = _create_http_error(500, url=item_path)

    # Page 3: Success (2 items)
    page3_response = _create_mock_response(
        200,
        {"results": [{"id": 7}, {"id": 8}], "_links": {}, "size": 2},
        url=page3_path,
    )

    # --- Side Effect Logic ---
    mock_get_call_paths: list[str] = []
    call_counts: dict[str, int] = {}

    def get_side_effect(
        path: str,
        params: dict[str, Any] | None = None,
        advanced_mode: bool = False,
    ) -> requests.Response:
        path = path.strip("/")
        mock_get_call_paths.append(path)
        call_counts[path] = call_counts.get(path, 0) + 1
        print(f"Mock GET received path: {path} (Call #{call_counts[path]})")

        if path == page1_path:
            print(f"-> Returning page 1 success for {path}")
            return page1_response
        elif path == page2_initial_path:
            print(f"-> Returning page 2 initial 500 error for {path}")
            return page2_initial_error
        elif path in page2_limit1_retry_errors:
            print(f"-> Returning page 2 limit=1 retry 500 error for {path}")
            return page2_limit1_retry_errors[path]
        elif path == page3_path:
            print(f"-> Returning page 3 success for {path}")
            return page3_response
        else:
            print(f"!!! Unexpected GET path in mock: {path}")
            raise RuntimeError(f"Unexpected GET path in mock: {path}")

    confluence_server_client._confluence.get.side_effect = get_side_effect

    # --- Execute ---
    results = list(
        confluence_server_client.paginated_cql_retrieval(
            cql=test_cql,
            limit=test_limit,
        )
    )

    # --- Assertions ---
    # Verify expected results (ids 1-3 from page 1, 7-8 from page 3)
    expected_results = [
        {"id": 1},
        {"id": 2},
        {"id": 3},  # Page 1
        # Page 2 completely skipped
        {"id": 7},
        {"id": 8},  # Page 3
    ]
    assert results == expected_results

    # Verify logs for the failed retry attempts on page 2
    for failed_path in page2_limit1_retry_errors:
        assert f"Error in confluence call to /{failed_path}" in caplog.text
    assert (
        f"Error in confluence call to {page2_initial_path}" not in caplog.text
    )  # Initial error triggers retry, not direct logging in _paginate_url

    # Verify sequence of calls
    expected_calls = [
        page1_path,  # Page 1 success
        page2_initial_path,  # Page 2 initial fail (500)
    ]
    # Add the failed limit=1 retry calls for page 2
    expected_calls.extend(list(page2_limit1_retry_errors.keys()))
    # The retry loop should make one final call to check if there are more items
    # expected_calls.append(page2_limit1_final_empty_path)
    # Add the call to page 3
    expected_calls.append(page3_path)

    assert mock_get_call_paths == expected_calls


def test_paginated_cql_retrieval_cloud_no_retry_on_error(
    mock_credentials_provider: mock.Mock,
) -> None:
    """
    Tests that for Confluence Cloud (is_cloud=True), paginated_cql_retrieval
    does NOT retry on pagination errors and raises HTTPError immediately.
    """
    # Setup Confluence Cloud Client
    confluence_cloud_client = OnyxConfluence(
        is_cloud=True,  # Key difference: Cloud instance
        url="https://fake-cloud.atlassian.net",
        credentials_provider=mock_credentials_provider,
        timeout=10,
    )
    mock_internal_client = mock.Mock()
    mock_internal_client.url = confluence_cloud_client._url
    confluence_cloud_client._confluence = mock_internal_client
    confluence_cloud_client._kwargs = confluence_cloud_client.shared_base_kwargs

    test_cql = "type=page"
    encoded_cql = "type%3Dpage"
    test_limit = 50  # Use a standard limit

    base_path = f"rest/api/content/search?cql={encoded_cql}"
    page1_path = f"{base_path}&limit={test_limit}"
    page2_path = f"{base_path}&limit={test_limit}&start={test_limit}"

    # --- Mock Responses ---
    # Page 1: Success
    page1_response = _create_mock_response(
        200,
        {
            "results": [{"id": i} for i in range(test_limit)],
            "_links": {"next": f"/{page2_path}"},
            "size": test_limit,
        },
        url=page1_path,
    )

    # Page 2: Failure (500)
    page2_error = _create_http_error(500, url=page2_path)

    # --- Side Effect Logic ---
    mock_get_call_paths: list[str] = []

    def get_side_effect(
        path: str,
        params: dict[str, Any] | None = None,
        advanced_mode: bool = False,
    ) -> requests.Response:
        path = path.strip("/")
        mock_get_call_paths.append(path)
        print(f"Mock GET received path: {path}")

        if path == page1_path:
            print(f"-> Returning page 1 success for {path}")
            return page1_response
        elif path == page2_path:
            print(f"-> Returning page 2 500 error for {path}")
            return page2_error
        else:
            # No other paths (like limit=1 retries) should be called
            print(f"!!! Unexpected GET path in mock for Cloud test: {path}")
            raise RuntimeError(f"Unexpected GET path in mock for Cloud test: {path}")

    confluence_cloud_client._confluence.get.side_effect = get_side_effect

    # --- Execute & Assert ---
    with pytest.raises(HTTPError) as excinfo:
        # Consume the iterator to trigger calls
        list(
            confluence_cloud_client.paginated_cql_retrieval(
                cql=test_cql,
                limit=test_limit,
            )
        )

    # Verify the error is the one we simulated for page 2
    assert excinfo.value.response == page2_error
    assert excinfo.value.response.status_code == 500
    assert page2_path in excinfo.value.response.url

    # Verify only two calls were made (page 1 success, page 2 fail)
    # Crucially, no retry attempts with different limits should exist.
    assert mock_get_call_paths == [page1_path, page2_path]
