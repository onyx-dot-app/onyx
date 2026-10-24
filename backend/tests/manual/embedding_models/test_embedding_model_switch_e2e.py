"""End-to-end embedding model switches against a live, disposable Onyx stack.

WARNING: this suite changes the target stack. Read README.md before you run it.
Opt in with ONYX_EMBEDDING_E2E_ALLOW_MUTATION=true. The tests run in file
order, so do not use -n:
1. The API refuses each LEGACY self-hosted model as a new target.
2. The API accepts a re-index to the live model. The suite cancels it.
3. For each target model: re-index to it, wait for the swap, and check that a
   pure vector search finds each seeded fact first.
"""

import os
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.server.documents.models import FileUploadResponse
from shared_configs.embedding_models import (
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelSpec,
    EmbeddingModelStatus,
    find_embedding_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider
from tests.integration.common_utils import http_client
from tests.integration.common_utils.constants import (
    API_SERVER_PORT,
    API_SERVER_URL,
    GENERAL_HEADERS,
)
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document_search import (
    DocumentSearchManager,
)
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.reindex_port import ReindexPortManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.manual.embedding_models.provider_env import provider_api_key

pytestmark = pytest.mark.skipif(
    os.environ.get("ONYX_EMBEDDING_E2E_ALLOW_MUTATION") != "true",
    reason="Changes the target stack. Set ONYX_EMBEDDING_E2E_ALLOW_MUTATION=true.",
)

SELECTABLE_BY_NAME = {
    spec.model_name: spec for spec in selectable_embedding_model_specs()
}
# Comma-separated exact model names, run in this order. The last one stays live.
_MODEL_NAMES = os.environ.get("ONYX_EMBEDDING_E2E_MODELS", "").split(",")
TARGETS = [
    SELECTABLE_BY_NAME[name.strip()] for name in _MODEL_NAMES if name.strip()
] or list(SELECTABLE_BY_NAME.values())
LEGACY_SELF_HOSTED = [
    spec
    for spec in EMBEDDING_MODEL_SPECS
    if spec.status == EmbeddingModelStatus.LEGACY and spec.provider_type is None
]
SWAP_TIMEOUT_SECONDS = float(
    os.environ.get("ONYX_EMBEDDING_E2E_TIMEOUT_SECONDS", "3600")
)
# A cloud target is probed before the API accepts it, and the first query after
# a swap can load the new model on the model server.
HTTP_TIMEOUT = httpx.Timeout(900.0, connect=10.0)

# (content, query). Each query is a paraphrase with little word overlap, so only
# the vectors can match it. The search still mixes in keyword scores, so a query
# must share no words with the other facts either.
FACTS: list[tuple[str, str]] = [
    (
        "Employees of the Halvorsen Robotics lab must wear anti-static wrist "
        "straps whenever they handle the prototype circuit boards.",
        "What protective gear does Halvorsen Robotics require when staff touch "
        "unfinished electronics?",
    ),
    (
        "The Pinecrest community garden waters its tomato beds with rainwater "
        "collected in three large barrels behind the tool shed.",
        "How are the vegetable plots at Pinecrest irrigated?",
    ),
    (
        "At Ostrander Middle School, students who forget their lunch can get a "
        "free sandwich from the front office before noon.",
        "What happens at Ostrander when a pupil arrives without the midday meal?",
    ),
    (
        "The Vellmar ferry stops running across the bay whenever wind speeds "
        "exceed forty knots.",
        "When is the Vellmar boat service suspended because of the weather?",
    ),
    (
        "Kestrel Analytics reimburses staff for up to two hundred dollars of "
        "home office furniture each calendar year.",
        "How much can Kestrel Analytics workers claim back each year for desks "
        "and chairs they buy for remote work?",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _live_api_server() -> Generator[None, None, None]:
    """Point the shared Manager client at the target stack."""
    # The Managers fall back to port 8080, the port of the normal dev stack.
    if (
        API_SERVER_PORT == "8080"
        and os.environ.get("ONYX_EMBEDDING_E2E_ALLOW_PORT_8080") != "true"
    ):
        pytest.fail(
            "Set API_SERVER_PORT to the api_server of a disposable stack. If the "
            "stack on port 8080 is disposable, set "
            "ONYX_EMBEDDING_E2E_ALLOW_PORT_8080=true."
        )
    with httpx.Client(
        transport=http_client.RetryingTransport(), timeout=HTTP_TIMEOUT
    ) as live_client:
        http_client.set_test_client(live_client)
        yield


@pytest.fixture(scope="module")
def admin() -> DATestUser:
    """An existing admin. The suite never creates users or resets the database."""
    return UserManager.login_as_user(
        DATestUser(
            id="",
            email=os.environ["ONYX_E2E_ADMIN_EMAIL"],
            password=os.environ["ONYX_E2E_ADMIN_PASSWORD"],
            headers=dict(GENERAL_HEADERS),
            # login_as_user sets the real values from /me.
            is_admin=False,
            is_active=True,
        )
    )


@pytest.fixture(scope="module")
def seeded_facts(admin: DATestUser) -> Generator[None, None, None]:
    """Index FACTS once through a File connector. Each switch re-embeds them.

    A File connector needs no license tier, unlike ingestion API keys. A clean-up
    failure fails the teardown, so leftovers show in the report.
    """
    response = FileManager.upload_connector_files(
        [(f"fact_{i}.txt", content.encode()) for i, (content, _) in enumerate(FACTS)],
        admin,
        content_type="text/plain",
    )
    response.raise_for_status()
    uploaded = FileUploadResponse(**response.json())
    started = datetime.now(timezone.utc)
    cc_pair = CCPairManager.create_from_scratch(
        user_performing_action=admin,
        source=DocumentSource.FILE,
        connector_specific_config={
            "file_locations": uploaded.file_paths,
            "file_names": uploaded.file_names,
            "zip_metadata_file_id": None,
        },
    )
    try:
        CCPairManager.wait_for_indexing_completion(
            cc_pair=cc_pair, after=started, user_performing_action=admin
        )
        # Fails before the first switch if the stack has no EE search API.
        DocumentSearchManager.search_documents(FACTS[0][1], admin, hybrid_alpha=1.0)
        yield
    finally:
        # The deletion task removes the seeded documents.
        CCPairManager.delete(cc_pair, user_performing_action=admin)


def _target_settings(spec: EmbeddingModelSpec) -> dict[str, Any]:
    """The search settings fields that select ``spec``."""
    return {
        "model_name": spec.model_name,
        "model_dim": spec.model_dim,
        "normalize": spec.normalize,
        "query_prefix": spec.query_prefix,
        "passage_prefix": spec.passage_prefix,
        "provider_type": spec.provider_type.value if spec.provider_type else None,
        "reduced_dimension": None,
    }


def _connect_provider(provider: EmbeddingProvider, admin: DATestUser) -> None:
    """Save the key from the provider's env var on the stack. Skips if unset."""
    response = client.put(
        f"{API_SERVER_URL}/admin/embedding/embedding-provider",
        json={
            "provider_type": provider.value,
            "api_key": provider_api_key(provider),
            "api_key_changed": True,
        },
        headers=admin.headers,
    )
    assert response.is_success, response.text


def _wait_for_swap(original_index_name: str, admin: DATestUser) -> dict[str, Any]:
    """Poll until the new index is live.

    A FAILED port unit retries on its own. A PAUSED unit waits for an operator,
    so it fails at once.
    """
    deadline = time.monotonic() + SWAP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        current = ReindexPortManager.get_current_settings(admin)
        if current["index_name"] != original_index_name:
            return current
        progress = ReindexPortManager.get_progress(admin)
        assert not progress.paused, (
            f"Port paused: {ReindexPortManager.get_errors(admin)}"
        )
        print(f"Waiting for the swap: {progress}")
        time.sleep(30)
    pytest.fail(
        f"No swap within {SWAP_TIMEOUT_SECONDS:.0f}s. Errors: "
        f"{ReindexPortManager.get_errors(admin)}"
    )


def _missed_queries(admin: DATestUser) -> list[str]:
    """The fact queries whose top pure vector search hit is not their fact."""
    return [
        query
        for content, query in FACTS
        if DocumentSearchManager.search_documents(query, admin, hybrid_alpha=1.0)[:1]
        != [content]
    ]


@pytest.mark.parametrize("legacy", LEGACY_SELF_HOSTED, ids=lambda spec: spec.model_name)
def test_legacy_target_is_rejected(
    legacy: EmbeddingModelSpec, admin: DATestUser
) -> None:
    current = ReindexPortManager.get_current_settings(admin)
    if (
        current.get("provider_type") is None
        and find_embedding_model_spec(None, current["model_name"]) == legacy
    ):
        pytest.skip("This legacy model is live. A same-model re-index is allowed.")
    response = ReindexPortManager.start_reindex_response(
        admin,
        acknowledged_wont_port_cc_pair_ids=[],
        settings_overrides=_target_settings(legacy),
    )
    if response.is_success:
        # Do not leave a re-index to a legacy model running.
        ReindexPortManager.cancel_reindex(admin)
    assert response.json().get("error_code") == OnyxErrorCode.INVALID_INPUT.code, (
        response.text
    )


def test_same_model_reindex_is_accepted(admin: DATestUser) -> None:
    # An empty consent list: the API refuses the re-index if it would delete
    # connectors (INVALID status), so the suite never deletes them.
    ReindexPortManager.wait_for_reindex_accepted(
        admin, acknowledged_wont_port_cc_pair_ids=[]
    )
    ReindexPortManager.cancel_reindex(admin)


@pytest.mark.usefixtures("seeded_facts")
@pytest.mark.parametrize("spec", TARGETS, ids=lambda spec: spec.model_name)
def test_switch_to_model(spec: EmbeddingModelSpec, admin: DATestUser) -> None:
    provider = spec.provider_type
    if provider is not None:
        _connect_provider(provider, admin)
    original_index_name = ReindexPortManager.get_current_settings(admin)["index_name"]
    ReindexPortManager.wait_for_reindex_accepted(
        admin,
        acknowledged_wont_port_cc_pair_ids=[],
        settings_overrides=_target_settings(spec),
    )
    try:
        current = _wait_for_swap(original_index_name, admin)
    except BaseException:
        # Do not leave a failed re-index running on the stack.
        ReindexPortManager.cancel_reindex(admin)
        raise
    assert (current["model_name"], current["model_dim"]) == (
        spec.model_name,
        spec.model_dim,
    )

    # The new index and the model server can take a short time to settle.
    deadline = time.monotonic() + 60
    missed = _missed_queries(admin)
    while missed and time.monotonic() < deadline:
        time.sleep(10)
        missed = _missed_queries(admin)
    assert not missed, f"Pure vector search with {spec.model_name} missed: {missed}"
