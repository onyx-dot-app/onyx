from http import HTTPStatus
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.document_index.document_index_utils import get_both_index_properties
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT


@pytest.mark.skip()
def test_vespa_update() -> None:
    """This Test exercises some ambiguous Vespa behavior and
    shows exactly what happens.
    """

    doc_id = "test-vespa-update"

    with Session(get_sqlalchemy_engine()) as db_session:
        primary_index_name, _, _, _ = get_both_index_properties(db_session)
        endpoint = (
            f"{DOCUMENT_ID_ENDPOINT.format(index_name=primary_index_name)}/{doc_id}"
        )
        with httpx.Client(http2=True) as http_client:
            payload: dict[str, Any] = {}

            # always delete to set up the test, should always be OK
            res = http_client.delete(endpoint)
            assert HTTPStatus.OK == res.status_code

            # Verify the document is not found
            res = http_client.get(endpoint)
            assert HTTPStatus.NOT_FOUND == res.status_code

            # Attempt to update a nonexistent test document. Should return OK
            payload["fields"] = {}
            payload["fields"]["title"] = {"assign": "Best of Bob Dylan"}

            res = http_client.put(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            assert HTTPStatus.OK == res.status_code

            # when we look for it, should be NOT_FOUND
            res = http_client.get(endpoint)
            assert HTTPStatus.NOT_FOUND == res.status_code

            # POST/Put new document
            payload = {}
            payload["fields"] = {}
            payload["fields"]["document_id"] = doc_id
            payload["fields"]["title"] = "A Head Full of Dreams"

            res = http_client.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            assert HTTPStatus.OK == res.status_code

            # when we look for it, now we should find it
            res = http_client.get(endpoint)
            assert HTTPStatus.OK == res.status_code
            d = res.json()

            assert payload["fields"]["title"] == d["fields"]["title"]

            # Attempt to update the document that we know exists. Should return OK
            payload["fields"] = {}
            payload["fields"]["title"] = {"assign": "Remember The Name"}

            res = http_client.put(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            assert HTTPStatus.OK == res.status_code

            # verify the change
            res = http_client.get(endpoint)
            assert HTTPStatus.OK == res.status_code
            d = res.json()
            assert payload["fields"]["title"]["assign"] == d["fields"]["title"]

            # always delete to clean up the test, should always be OK
            res = http_client.delete(endpoint)
            assert HTTPStatus.OK == res.status_code

            # Verify the document is not found
            res = http_client.get(endpoint)
            assert HTTPStatus.NOT_FOUND == res.status_code
