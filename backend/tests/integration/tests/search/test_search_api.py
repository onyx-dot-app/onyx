"""Integration tests for the Search API (POST /api/search)."""

from __future__ import annotations

import os

import pytest
import requests

from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

SEARCH_URL = f"{API_SERVER_URL}/search"


def _search(
    query: str,
    user: DATestUser,
    **kwargs: object,
) -> requests.Response:
    return requests.post(
        SEARCH_URL,
        json={"query": query, **kwargs},
        headers=user.headers,
    )


def test_basic_search_returns_results(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    doc_content = "search api integration test unique document"
    doc = DocumentManager.seed_doc_with_content(cc_pair, doc_content, api_key)

    resp = _search(doc_content, admin_user)
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["results"]) > 0
    assert isinstance(data["llm_facing_text"], str)
    assert len(data["llm_facing_text"]) > 0
    assert isinstance(data["citation_mapping"], dict)

    result = data["results"][0]
    assert result["document_id"] == doc.id
    assert result["citation_id"] is not None
    assert result["source_type"] is not None
    assert result["blurb"] is not None


def test_document_set_filtering(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair_in = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    cc_pair_out = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    shared_phrase = "docset-filter-unique-phrase"
    doc_in = DocumentManager.seed_doc_with_content(
        cc_pair_in,
        f"{shared_phrase} included",
        api_key,
    )
    doc_out = DocumentManager.seed_doc_with_content(
        cc_pair_out,
        f"{shared_phrase} excluded",
        api_key,
    )

    doc_set = DocumentSetManager.create(
        cc_pair_ids=[cc_pair_in.id],
        user_performing_action=admin_user,
    )
    DocumentSetManager.wait_for_sync(
        user_performing_action=admin_user,
        document_sets_to_check=[doc_set],
    )

    resp = _search(shared_phrase, admin_user, document_sets=[doc_set.name])
    assert resp.status_code == 200

    result_doc_ids = {r["document_id"] for r in resp.json()["results"]}
    assert doc_in.id in result_doc_ids
    assert doc_out.id not in result_doc_ids


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)
def test_acl_enforcement(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    privileged_user = UserManager.create(name="search-acl-allowed")
    blocked_user = UserManager.create(name="search-acl-blocked")

    restricted_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        user_performing_action=admin_user,
    )

    user_group = UserGroupManager.create(
        user_ids=[privileged_user.id],
        cc_pair_ids=[restricted_cc_pair.id],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
        user_groups_to_check=[user_group],
    )

    doc_content = "restricted acl search document"
    doc = DocumentManager.seed_doc_with_content(
        restricted_cc_pair, doc_content, api_key
    )

    allowed_resp = _search(doc_content, privileged_user)
    assert allowed_resp.status_code == 200
    allowed_doc_ids = {r["document_id"] for r in allowed_resp.json()["results"]}
    assert doc.id in allowed_doc_ids

    blocked_resp = _search(doc_content, blocked_user)
    assert blocked_resp.status_code == 200
    assert len(blocked_resp.json()["results"]) == 0


def test_persona_scoped_search(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair_in = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    cc_pair_out = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    shared_phrase = "persona-scope-unique-phrase"
    doc_in = DocumentManager.seed_doc_with_content(
        cc_pair_in,
        f"{shared_phrase} in scope",
        api_key,
    )
    doc_out = DocumentManager.seed_doc_with_content(
        cc_pair_out,
        f"{shared_phrase} out of scope",
        api_key,
    )

    doc_set = DocumentSetManager.create(
        cc_pair_ids=[cc_pair_in.id],
        user_performing_action=admin_user,
    )
    DocumentSetManager.wait_for_sync(
        user_performing_action=admin_user,
        document_sets_to_check=[doc_set],
    )

    persona = PersonaManager.create(
        user_performing_action=admin_user,
        document_set_ids=[doc_set.id],
        is_public=True,
    )

    resp = _search(shared_phrase, admin_user, persona_id=persona.id)
    assert resp.status_code == 200

    result_doc_ids = {r["document_id"] for r in resp.json()["results"]}
    assert doc_in.id in result_doc_ids
    assert doc_out.id not in result_doc_ids


def test_invalid_persona_returns_404(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    resp = _search("test", admin_user, persona_id=99999)
    assert resp.status_code == 404


def test_unauthenticated_returns_401(
    reset: None,  # noqa: ARG001
) -> None:
    resp = requests.post(
        SEARCH_URL,
        json={"query": "test"},
    )
    assert resp.status_code == 403
