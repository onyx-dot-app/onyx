import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.freshdesk_solutions.connector import FreshdeskSolutionsConnector
from onyx.connectors.models import Document


@pytest.fixture
def freshdesk_solutions_connector() -> FreshdeskSolutionsConnector:
    connector = FreshdeskSolutionsConnector()
    connector.load_credentials(
        {
            "freshdesk_solution_domain": os.environ["FRESHDESK_SOLUTION_DOMAIN"],
            "freshdesk_solution_api_key": os.environ["FRESHDESK_SOLUTION_API_KEY"],
            "freshdesk_solution_password": os.environ["FRESHDESK_SOLUTION_PASSWORD"],
        }
    )
    return connector


@pytest.mark.xfail(
    reason=(
        "Requires a stable Freshdesk Solutions sandbox with fixtures "
        "and CI secrets configured."
    )
)
def test_freshdesk_solutions_connector_basic(
    freshdesk_solutions_connector: FreshdeskSolutionsConnector,
) -> None:
    first_batch = next(freshdesk_solutions_connector.poll_source(0, time.time()))

    assert len(first_batch) > 0
    target_doc = first_batch[0]
    assert isinstance(target_doc, Document)
    assert target_doc.source == DocumentSource.FRESHDESK_SOLUTIONS
    assert len(target_doc.sections) > 0
