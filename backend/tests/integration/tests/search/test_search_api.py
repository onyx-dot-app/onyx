"""Integration tests for the Search API (POST /api/search)."""

from __future__ import annotations

import os

import httpx
import pytest

from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
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
) -> httpx.Response:
    return client.post(
        SEARCH_URL,
        json={"query": query, **kwargs},
        headers=user.headers,
    )


def test_basic_search_returns_results(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    doc_content = "search api integration test unique document"
    DocumentManager.seed_doc_with_content(cc_pair, doc_content, api_key)

    resp = _search(doc_content, admin_user)
    assert resp.status_code == 200

    # ``reset`` only wipes Postgres; OpenSearch is shared across tests, so docs
    # seeded by prior tests may still match. Find the seeded doc by content
    # rather than asserting on result count.
    data = resp.json()
    matches = [r for r in data["results"] if doc_content in r["content"]]
    assert len(matches) == 1
    assert matches[0]["citation_id"] is not None
    assert matches[0]["source_type"]


def test_document_set_filtering(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair_in = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    cc_pair_out = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    shared_phrase = "docset-filter-unique-phrase"
    # The two contents share ``shared_phrase`` but the unique suffixes
    # ("included" / "excluded") must not be substrings of each other —
    # otherwise the negative assertion below silently becomes vacuous.
    included_content = f"{shared_phrase} included"
    excluded_content = f"{shared_phrase} excluded"
    DocumentManager.seed_doc_with_content(cc_pair_in, included_content, api_key)
    DocumentManager.seed_doc_with_content(cc_pair_out, excluded_content, api_key)

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

    contents = [r["content"] for r in resp.json()["results"]]
    assert any(included_content in c for c in contents)
    assert not any(excluded_content in c for c in contents)


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group permissions are Enterprise-only",
)
def test_acl_enforcement(
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
    DocumentManager.seed_doc_with_content(restricted_cc_pair, doc_content, api_key)

    allowed_resp = _search(doc_content, privileged_user)
    assert allowed_resp.status_code == 200
    allowed_contents = [r["content"] for r in allowed_resp.json()["results"]]
    assert any(doc_content in c for c in allowed_contents)

    blocked_resp = _search(doc_content, blocked_user)
    assert blocked_resp.status_code == 200
    # OpenSearch is not reset between tests, so prior tests' PUBLIC docs may
    # still satisfy the query and surface here. Assert on the specific private
    # doc rather than total result count.
    blocked_contents = [r["content"] for r in blocked_resp.json()["results"]]
    assert not any(doc_content in c for c in blocked_contents)


def test_persona_scoped_search(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    api_key: DATestAPIKey,
) -> None:
    cc_pair_in = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    cc_pair_out = CCPairManager.create_from_scratch(user_performing_action=admin_user)

    shared_phrase = "persona-scope-unique-phrase"
    # Suffixes ("in scope" / "out of scope") must not be substrings of each
    # other so the negative assertion below stays meaningful.
    included_content = f"{shared_phrase} in scope"
    excluded_content = f"{shared_phrase} out of scope"
    DocumentManager.seed_doc_with_content(cc_pair_in, included_content, api_key)
    DocumentManager.seed_doc_with_content(cc_pair_out, excluded_content, api_key)

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

    contents = [r["content"] for r in resp.json()["results"]]
    assert any(included_content in c for c in contents)
    assert not any(excluded_content in c for c in contents)


def test_invalid_persona_returns_404(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    resp = _search("test", admin_user, persona_id=99999)
    assert resp.status_code == 404


def test_unauthenticated_returns_401() -> None:
    resp = client.post(
        SEARCH_URL,
        json={"query": "test"},
    )
    assert resp.status_code == 403
