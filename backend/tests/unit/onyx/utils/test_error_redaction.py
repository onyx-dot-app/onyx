import json
import logging
from unittest.mock import MagicMock, Mock

import pytest
import requests
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from onyx.chat import errors, process_message
from onyx.chat.errors import EmptyLLMResponseError
from onyx.chat.models import StreamingError
from onyx.connectors import connector_runner
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import ConnectorCheckpoint
from onyx.llm.models import ToolChoiceOptions
from onyx.main import validation_exception_handler
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils import retry_wrapper


def test_retry_logs_hide_headers_and_default_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retry_wrapper, "logger", logging.getLogger(__name__))
    response = requests.Response()
    response.status_code = 400
    request = Mock(return_value=response)
    monkeypatch.setattr(retry_wrapper.requests, "request", request)
    headers = {"Authorization": "header-secret", "X-Custom-Key": "custom-secret"}
    body = {"password": "body-secret"}

    with pytest.raises(requests.HTTPError):
        retry_wrapper.request_with_retries(
            "POST", "https://example.com", headers=headers, data=body, tries=1
        )

    assert "Request failed" in caplog.text
    assert all(
        value not in caplog.text for value in [*headers.values(), *body.values()]
    )
    assert request.call_args.kwargs["headers"] == headers
    assert request.call_args.kwargs["data"] == body


def test_connector_failure_does_not_log_frame_locals(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(connector_runner, "logger", logging.getLogger(__name__))
    connector = Mock(spec=LoadConnector)
    connector.build_dummy_checkpoint.return_value = ConnectorCheckpoint(has_more=True)

    def fail() -> None:
        credential = "connector-secret"
        raise RuntimeError(credential)

    connector.load_from_state.side_effect = fail
    runner = connector_runner.ConnectorRunner[ConnectorCheckpoint](
        connector=connector, batch_size=10, include_permissions=False
    )
    with pytest.raises(RuntimeError, match="connector-secret"):
        list(runner.run(ConnectorCheckpoint(has_more=True)))

    assert "RuntimeError" in caplog.text
    assert "connector-secret" not in caplog.text


def test_validation_failure_hides_input_and_exception_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("onyx.main.logger", logging.getLogger(__name__))
    request = Request({"type": "http", "method": "POST", "path": "/test"})
    error = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "validation-secret"),
                "msg": "Invalid value: validation-secret",
                "input": "validation-secret",
            }
        ]
    )
    try:
        raise error
    except RequestValidationError as exc:
        response = validation_exception_handler(request, exc)

    payload = json.loads(bytes(response.body))
    assert response.status_code == 422
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["message"] == payload["detail"]
    assert caplog.records
    assert "validation-secret" not in caplog.text
    assert "validation-secret" not in bytes(response.body).decode()


def test_chat_traceback_only_reaches_development_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        process_message,
        "prepare_chat_turn",
        Mock(side_effect=RuntimeError("internal-frame-detail")),
    )
    for dev_mode in (False, True):
        monkeypatch.setattr(errors, "DEV_MODE", dev_mode)
        packets = list(
            process_message.handle_stream_message_objects(
                new_msg_req=SendMessageRequest(message="test"), user=Mock()
            )
        )
        assert len(packets) == 1
        error = packets[0]
        assert isinstance(error, StreamingError)
        assert error.error_code == "INIT_FAILED"
        if dev_mode:
            assert error.stack_trace and "internal-frame-detail" in error.stack_trace
        else:
            assert error.stack_trace is None


def test_retry_logs_hide_url_params_and_exception_on_every_attempt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retry_wrapper, "logger", logging.getLogger(__name__))
    response = requests.Response()
    response.status_code = 400
    response.url = (
        "https://user:credential-secret@example.com/path-secret?key=query-secret"
    )
    response.reason = "reason-secret"
    request = Mock(return_value=response)
    monkeypatch.setattr(retry_wrapper.requests, "request", request)
    params = {"token": "params-secret"}
    with pytest.raises(requests.HTTPError):
        retry_wrapper.request_with_retries(
            "GET", response.url, params=params, tries=2, delay=0
        )
    assert request.call_count == 2
    assert request.call_args.kwargs["url"] == response.url
    assert request.call_args.kwargs["params"] == params
    assert caplog.text.count("Request failed") == 2
    assert "secret" not in caplog.text
    assert "400" in caplog.text


@pytest.mark.parametrize("empty_response", [True, False])
def test_chat_provider_tracebacks_only_reach_development_clients(
    monkeypatch: pytest.MonkeyPatch, empty_response: bool
) -> None:
    setup = MagicMock()
    setup.incognito_record_mode = None
    setup.initial_packets = []
    llm = setup.responses[0].llm
    llm.info.model_name = "test-model"
    llm.info.model_provider = "test-provider"
    llm.redact_error.side_effect = lambda text: text
    monkeypatch.setattr(process_message, "prepare_chat_turn", Mock(return_value=setup))
    monkeypatch.setattr(process_message, "StreamBufferWriter", MagicMock())
    monkeypatch.setattr(process_message, "get_control_cache_backend", MagicMock())
    failure = (
        EmptyLLMResponseError(
            provider="test-provider",
            model="test-model",
            tool_choice=ToolChoiceOptions.AUTO,
            client_error_msg="Empty response",
        )
        if empty_response
        else RuntimeError("internal-provider-frame")
    )
    monkeypatch.setattr(process_message, "start_chat_turn", Mock(side_effect=failure))
    for dev_mode in (False, True):
        monkeypatch.setattr(errors, "DEV_MODE", dev_mode)
        packets = list(
            process_message.handle_stream_message_objects(
                new_msg_req=SendMessageRequest(message="test"), user=Mock()
            )
        )
        assert len(packets) == 1
        error = packets[0]
        assert isinstance(error, StreamingError)
        assert error.error_code != "INIT_FAILED"
        if empty_response:
            assert error.error_code == "EMPTY_LLM_RESPONSE"
        if dev_mode:
            assert error.stack_trace and "Traceback" in error.stack_trace
            if not empty_response:
                assert "internal-provider-frame" in error.stack_trace
        else:
            assert error.stack_trace is None
            assert "internal-provider-frame" not in error.error


@pytest.mark.parametrize("failure_type", [requests.ConnectionError, requests.Timeout])
def test_request_failures_log_type_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_type: type[requests.RequestException],
) -> None:
    monkeypatch.setattr(retry_wrapper, "logger", logging.getLogger(__name__))
    request = Mock(side_effect=failure_type("transport-secret"))
    monkeypatch.setattr(retry_wrapper.requests, "request", request)
    with pytest.raises(failure_type, match="transport-secret"):
        retry_wrapper.request_with_retries(
            "POST", "https://example.com/path-secret", tries=2, delay=0
        )
    assert request.call_count == 2
    assert caplog.text.count("Request failed") == 2
    assert failure_type.__name__ in caplog.text
    assert "POST" in caplog.text
    assert "secret" not in caplog.text
