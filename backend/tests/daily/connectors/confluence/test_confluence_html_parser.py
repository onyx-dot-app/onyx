import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import Document
from onyx.file_processing.enums import HtmlBasedConnectorTransformLinksStrategy
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

_PARSER_REGRESSION_SPACE = "ParserReg"
_LINK_PAGE_TITLE = "HTML Parser Regression - Link Scope"
_TABLE_PAGE_TITLE = "HTML Parser Regression - Table Scope"
_LINK_TARGET = "https://example.com/parser-regression-target"

pytestmark = pytest.mark.secrets(TestSecret.CONFLUENCE_ACCESS_TOKEN)


def _make_connector(access_token: str) -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base=os.environ["CONFLUENCE_TEST_SPACE_URL"],
        space=_PARSER_REGRESSION_SPACE,
        is_cloud=True,
    )
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            None,
            DocumentSource.CONFLUENCE,
            {
                "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
                "confluence_access_token": access_token,
            },
        )
    )
    return connector


@pytest.fixture(scope="module")
def parser_regression_documents(
    test_secrets: dict[TestSecret, str],
) -> dict[str, Document]:
    connector = _make_connector(
        test_secrets[TestSecret.CONFLUENCE_ACCESS_TOKEN].strip()
    )
    with patch(
        "onyx.file_processing.html_utils.HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY",
        HtmlBasedConnectorTransformLinksStrategy.MARKDOWN,
    ):
        result = load_all_from_connector(connector, 0, time.time())

    return {document.semantic_identifier: document for document in result.documents}


def test_confluence_html_link_scope(
    parser_regression_documents: dict[str, Document],
) -> None:
    document = parser_regression_documents[_LINK_PAGE_TITLE]

    assert document.sections[0].text == (
        f"LINK_BEFORE [LINK_TARGET_ONLY]({_LINK_TARGET}) "
        "LINK_AFTER_MUST_NOT_BE_CLICKABLE\n"
        "LINK_NEXT_PARAGRAPH_MUST_NOT_BE_CLICKABLE"
    )


def test_confluence_html_table_scope(
    parser_regression_documents: dict[str, Document],
) -> None:
    document = parser_regression_documents[_TABLE_PAGE_TITLE]

    assert document.sections[0].text == (
        "TABLE_BEFORE\n"
        "\tHEADER_ALPHA\tHEADER_BETA\n"
        "\tCELL_ALPHA\tCELL_BETA_LINE_1 CELL_BETA_LINE_2\n"
        "TABLE_AFTER_HEADING\n"
        "TABLE_AFTER_PARAGRAPH_MUST_BE_SEPARATE\n"
        "- TABLE_AFTER_LIST_ONE\n"
        "- TABLE_AFTER_LIST_TWO"
    )
