"""Jira utils used internally."""

from __future__ import annotations

import threading
import warnings
from typing import Any, cast

from requests import Response
from requests.structures import CaseInsensitiveDict as _CaseInsensitiveDict

from jira.resilientsession import raise_on_error


class CaseInsensitiveDict(_CaseInsensitiveDict):
    """A case-insensitive ``dict``-like object.

    DEPRECATED: use requests.structures.CaseInsensitiveDict directly.

    Implements all methods and operations of
    ``collections.MutableMapping`` as well as dict's ``copy``. Also
    provides ``lower_items``.

    All keys are expected to be strings. The structure remembers the
    case of the last key to be set, and ``iter(instance)``,
    ``keys()``, ``items()``, ``iterkeys()``
    will contain case-sensitive keys. However, querying and contains
    testing is case insensitive::

        cid = CaseInsensitiveDict()
        cid['Accept'] = 'application/json'
        cid['accept'] == 'application/json'  # True
        list(cid) == ['Accept']  # True

    For example, ``headers['content-encoding']`` will return the
    value of a ``'Content-Encoding'`` response header, regardless
    of how the header name was originally stored.

    If the constructor, ``.update``, or equality comparison
    operations are given keys that have equal ``.lower()`` s, the
    behavior is undefined.

    """

    def __init__(self, *args, **kwargs) -> None:
        warnings.warn(
            "Use requests.structures.CaseInsensitiveDict directly", DeprecationWarning
        )
        super().__init__(*args, **kwargs)


def threaded_requests(requests):
    for fn, url, request_args in requests:
        th = threading.Thread(target=fn, args=(url,), kwargs=request_args, name=url)
        th.start()

    for th in threading.enumerate():
        if th.name.startswith("http"):
            th.join()


def json_loads(resp: Response | None) -> Any:
    """Attempts to load json the result of a response.

    Args:
        resp (Optional[Response]): The Response object

    Raises:
        JIRAError: via :py:func:`jira.resilientsession.raise_on_error`

    Returns:
        Union[List[Dict[str, Any]], Dict[str, Any]]: the json
    """
    raise_on_error(resp)  # if 'resp' is None, will raise an error here
    resp = cast(Response, resp)  # tell mypy only Response-like are here
    try:
        return resp.json()
    except ValueError:
        # json.loads() fails with empty bodies
        if not resp.text:
            return {}
        raise


def remove_empty_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """A convenience function to remove key/value pairs with `None` for a value.

    Args:
      data: A dictionary.

    Returns:
      Dict[str, Any]: A dictionary with no `None` key/value pairs.
    """
    return {key: val for key, val in data.items() if val is not None}
