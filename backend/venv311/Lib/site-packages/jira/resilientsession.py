from __future__ import annotations

import abc
import json
import logging
import random
import time
from http import HTTPStatus
from typing import Any

from requests import Response, Session
from requests.exceptions import ConnectionError
from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeGuard

from jira.exceptions import JIRAError

LOG = logging.getLogger(__name__)


class PrepareRequestForRetry(metaclass=abc.ABCMeta):
    """This class allows for the manipulation of the Request keyword arguments before a retry.

    The :py:meth:`.prepare` handles the processing of the Request keyword arguments.
    """

    @abc.abstractmethod
    def prepare(
        self, original_request_kwargs: CaseInsensitiveDict
    ) -> CaseInsensitiveDict:
        """Process the Request's keyword arguments before retrying the Request.

        Args:
            original_request_kwargs (CaseInsensitiveDict): The keyword arguments of the Request.

        Returns:
            CaseInsensitiveDict: The new keyword arguments to use in the retried Request.
        """
        return original_request_kwargs


class PassthroughRetryPrepare(PrepareRequestForRetry):
    """Returns the Request's keyword arguments unchanged, when no change needs to be made before a retry."""

    def prepare(
        self, original_request_kwargs: CaseInsensitiveDict
    ) -> CaseInsensitiveDict:
        return super().prepare(original_request_kwargs)


def raise_on_error(resp: Response | None, **kwargs) -> TypeGuard[Response]:
    """Handle errors from a Jira Request.

    Args:
        resp (Optional[Response]): Response from Jira request

    Raises:
        JIRAError: If Response is None
        JIRAError: for unhandled 400 status codes.

    Returns:
        TypeGuard[Response]: True if the passed in Response is all good.
    """
    request = kwargs.get("request", None)

    if resp is None:
        raise JIRAError("Empty Response!", response=resp, **kwargs)

    if not resp.ok:
        error = parse_error_msg(resp=resp)

        raise JIRAError(
            error,
            status_code=resp.status_code,
            url=resp.url,
            request=request,
            response=resp,
            **kwargs,
        )

    return True  # if no exception was raised, we have a valid Response


def parse_errors(resp: Response) -> list[str]:
    """Parse a Jira Error messages from the Response.

    https://developer.atlassian.com/cloud/jira/platform/rest/v2/intro/#status-codes

    Args:
        resp (Response): The Jira API request's response.

    Returns:
        List[str]: The error messages list parsed from the Response. An empty list if no error.
    """
    resp_data: dict[str, Any] = {}  # json parsed from the response
    parsed_errors: list[str] = []  # error messages parsed from the response
    if resp.status_code == 403 and "x-authentication-denied-reason" in resp.headers:
        return [resp.headers["x-authentication-denied-reason"]]
    elif resp.text:
        try:
            resp_data = resp.json()
        except ValueError:
            return [resp.text]

    if "message" in resp_data:
        # Jira 5.1 errors
        parsed_errors = [resp_data["message"]]
    if "errorMessage" in resp_data:
        # Sometimes Jira returns `errorMessage` as a message error key
        # for example for the "Service temporary unavailable" error
        parsed_errors = [resp_data["errorMessage"]]
    if "errorMessages" in resp_data:
        # Jira 5.0.x error messages sometimes come wrapped in this array
        # Sometimes this is present but empty
        error_messages = resp_data["errorMessages"]
        if len(error_messages) > 0:
            if isinstance(error_messages, list | tuple):
                parsed_errors = list(error_messages)
            else:
                parsed_errors = [error_messages]
    if "errors" in resp_data:
        resp_errors = resp_data["errors"]
        if len(resp_errors) > 0 and isinstance(resp_errors, dict):
            # Catching only 'errors' that are dict. See https://github.com/pycontribs/jira/issues/350
            # Jira 6.x error messages are found in this array.
            parsed_errors = [str(err) for err in resp_errors.values()]

    return parsed_errors


def parse_error_msg(resp: Response) -> str:
    """Parse a Jira Error messages from the Response and join them by comma.

    https://developer.atlassian.com/cloud/jira/platform/rest/v2/intro/#status-codes

    Args:
        resp (Response): The Jira API request's response.

    Returns:
        str: The error message parsed from the Response. An empty str if no error.
    """
    errors = parse_errors(resp)
    return ", ".join(errors)


class ResilientSession(Session):
    """This class is supposed to retry requests that do return temporary errors.

    :py:meth:`__recoverable` handles all retry-able errors.
    """

    def __init__(self, timeout=None, max_retries: int = 3, max_retry_delay: int = 60):
        """A Session subclass catered for the Jira API with exponential delaying retry.

        Args:
            timeout (Optional[Union[Union[float, int], Tuple[float, float]]]): Connection/read timeout delay. Defaults to None.
            max_retries (int): Max number of times to retry a request. Defaults to 3.
            max_retry_delay (int): Max delay allowed between retries. Defaults to 60.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_retry_delay = max_retry_delay
        super().__init__()

        # Indicate our preference for JSON to avoid https://bitbucket.org/bspeakmon/jira-python/issue/46 and https://jira.atlassian.com/browse/JRA-38551
        self.headers.update({"Accept": "application/json,*/*;q=0.9"})

        # Warn users on instantiation the debug level shouldn't be used for prod
        LOG.debug(
            "WARNING: On error, will dump Response headers and body to logs. "
            + f"Log level debug in '{__name__}' is not safe for production code!"
        )

    def _jira_prepare(self, **original_kwargs) -> dict:
        """Do any pre-processing of our own and return the updated kwargs."""
        prepared_kwargs = original_kwargs.copy()
        self.headers: CaseInsensitiveDict
        request_headers = self.headers.copy()
        request_headers.update(original_kwargs.get("headers", {}))
        prepared_kwargs["headers"] = request_headers

        data = original_kwargs.get("data", None)
        if isinstance(data, dict) and data:
            # mypy ensures we don't do this,
            # but for people subclassing we should preserve old behaviour
            prepared_kwargs["data"] = json.dumps(data)

        if "verify" not in prepared_kwargs:
            prepared_kwargs["verify"] = self.verify

        return prepared_kwargs

    def request(  # type: ignore[override] # An intentionally different override
        self,
        method: str,
        url: str | bytes,
        _prepare_retry_class: PrepareRequestForRetry = PassthroughRetryPrepare(),
        **kwargs,
    ) -> Response:
        """This is an intentional override of `Session.request()` to inject some error handling and retry logic.

        Raises:
            Exception: Various exceptions as defined in py:method:`raise_on_error`.

        Returns:
            Response: The response.
        """
        retry_number = 0
        exception: Exception | None = None
        response: Response | None = None
        response_or_exception: ConnectionError | Response | None

        processed_kwargs = self._jira_prepare(**kwargs)

        def is_allowed_to_retry() -> bool:
            """Helper method to say if we should still be retrying."""
            return retry_number <= self.max_retries

        while is_allowed_to_retry():
            response = None
            exception = None

            try:
                response = super().request(
                    method, url, timeout=self.timeout, **processed_kwargs
                )
                if response.ok:
                    self.__handle_known_ok_response_errors(response)
                    return response
            # Can catch further exceptions as required below
            except ConnectionError as e:
                exception = e

            # Decide if we should keep retrying
            response_or_exception = response if response is not None else exception
            retry_number += 1
            if is_allowed_to_retry() and self.__recoverable(
                response_or_exception, url, method.upper(), retry_number
            ):
                _prepare_retry_class.prepare(processed_kwargs)  # type: ignore[arg-type] # Dict and CaseInsensitiveDict are fine here
            else:
                retry_number = self.max_retries + 1  # exit the while loop, as above max

        if exception is not None:
            # We got an exception we could not recover from
            raise exception
        elif raise_on_error(response, **processed_kwargs):
            # raise_on_error will raise an exception if the response is invalid
            return response
        else:
            # Shouldn't reach here...(but added for mypy's benefit)
            raise RuntimeError("Expected a Response or Exception to raise!")

    def __handle_known_ok_response_errors(self, response: Response):
        """Responses that report ok may also have errors.

        We can either log the error or raise the error as appropriate here.

        Args:
            response (Response): The response.
        """
        if not response.ok:
            return  # We use self.__recoverable() to handle these
        if (
            len(response.content) == 0
            and "X-Seraph-LoginReason" in response.headers
            and "AUTHENTICATED_FAILED" in response.headers["X-Seraph-LoginReason"]
        ):
            LOG.warning("Atlassian's bug https://jira.atlassian.com/browse/JRA-41559")

    def __recoverable(
        self,
        response: ConnectionError | Response | None,
        url: str | bytes,
        request_method: str,
        counter: int = 1,
    ):
        """Return whether the request is recoverable and hence should be retried.

        Exponentially delays if recoverable.

        At this moment it supports: 429, 503

        Args:
            response (Optional[Union[ConnectionError, Response]]): The response or exception.
              Note: the response here is expected to be ``not response.ok``.
            url (Union[str, bytes]): The URL.
            request_method (str): The request method.
            counter (int, optional): The retry counter to use when calculating the exponential delay. Defaults to 1.

        Returns:
            bool: True if the request should be retried.
        """
        suggested_delay = -1  # Controls return value AND whether we delay or not, Not-recoverable by default
        msg = str(response)

        if isinstance(response, ConnectionError):
            suggested_delay = 10 * 2**counter

            LOG.warning(
                f"Got ConnectionError [{response}] errno:{response.errno} on {request_method} "
                + f"{url}\n"  # type: ignore[str-bytes-safe]
            )
            if LOG.level > logging.DEBUG:
                LOG.warning(
                    "Response headers for ConnectionError are only printed for log level DEBUG."
                )

        elif isinstance(response, Response):
            recoverable_error_codes = [
                HTTPStatus.TOO_MANY_REQUESTS,
                HTTPStatus.SERVICE_UNAVAILABLE,
            ]

            if response.status_code in recoverable_error_codes:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    suggested_delay = 2 * max(
                        int(retry_after), 1
                    )  # Do as told but always wait at least a little
                elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    suggested_delay = 10 * 2**counter  # Exponential backoff

                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    msg = f"{response.status_code} {response.reason}"
                    self.__log_http_429_response(response)

        is_recoverable = suggested_delay > 0
        if is_recoverable:
            # Apply jitter to prevent thundering herd
            delay = min(self.max_retry_delay, suggested_delay) * random.uniform(
                0.5, 1.0
            )
            LOG.warning(
                f"Got recoverable error from {request_method} {url}, will retry [{counter}/{self.max_retries}] in {delay}s. Err: {msg}"  # type: ignore[str-bytes-safe]
            )
            if isinstance(response, Response):
                LOG.debug(
                    "response.headers:\n%s",
                    json.dumps(dict(response.headers), indent=4),
                )
                LOG.debug("response.body:\n%s", response.content)
            time.sleep(delay)

        return is_recoverable

    def __log_http_429_response(self, response: Response):
        retry_after = response.headers.get("Retry-After")
        number_of_tokens_issued_per_interval = response.headers.get(
            "X-RateLimit-FillRate"
        )
        token_issuing_rate_interval_seconds = response.headers.get(
            "X-RateLimit-Interval-Seconds"
        )
        maximum_number_of_tokens = response.headers.get("X-RateLimit-Limit")

        warning_msg = "Request rate limited by Jira."
        warning_msg += (
            f" Request should be retried after {retry_after} seconds.\n"
            if retry_after is not None
            else "\n"
        )

        if (
            number_of_tokens_issued_per_interval is not None
            and token_issuing_rate_interval_seconds is not None
        ):
            warning_msg += f"{number_of_tokens_issued_per_interval} tokens are issued every {token_issuing_rate_interval_seconds} seconds.\n"

        if maximum_number_of_tokens is not None:
            warning_msg += (
                f"You can accumulate up to {maximum_number_of_tokens} tokens.\n"
            )

        warning_msg = (
            warning_msg
            + "Consider adding an exemption for the user as explained in: "
            + "https://confluence.atlassian.com/adminjiraserver/improving-instance-stability-with-rate-limiting-983794911.html"
        )

        LOG.warning(warning_msg)
