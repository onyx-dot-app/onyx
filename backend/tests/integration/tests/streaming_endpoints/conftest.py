from collections.abc import Callable

import pytest

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import SimpleTestDocument


DocumentBuilderType = Callable[[list[str]], list[SimpleTestDocument]]


@pytest.fixture
def document_builder(admin_user: DATestUser) -> DocumentBuilderType:
    api_key: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )

    # create connector
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    def _document_builder(contents: list[str]) -> list[SimpleTestDocument]:
        # seed documents
        docs: list[SimpleTestDocument] = [
            DocumentManager.seed_doc_with_content(
                cc_pair=cc_pair_1,
                content=content,
                api_key=api_key,
            )
            for content in contents
        ]

        return docs

    return _document_builder
