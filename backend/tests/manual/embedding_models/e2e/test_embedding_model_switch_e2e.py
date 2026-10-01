"""End-to-end embedding-model switches against a live Onyx stack.

WARNING: this suite changes the target deployment. It re-embeds every document
on the stack once per target model and leaves the last target as the live
(PRESENT) model. The upgrade-only rule then blocks a return to a legacy model
through the API. Each re-index consents to deleting every connector in INVALID
status (the API requires that consent), so the clean-up after the swap deletes
those connectors and their documents. The suite stops before any change if such
connectors exist, unless ``ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION=true``.
Run it only against a disposable stack or one you can restore.

Opt in with BOTH ``ONYX_EMBEDDING_E2E=true`` and
``ONYX_EMBEDDING_E2E_ALLOW_MUTATION=true``. See the README next to this
directory for the env vars and exact commands.

The tests run in file order (do not use ``-n``):
1. Every LEGACY registry model is refused as a new target (4xx).
2. A re-index to the PRESENT model is accepted, then cancelled.
3. For each target model (``ONYX_EMBEDDING_E2E_MODELS``, default: every
   SELECTABLE model, cloud ones only when their key env var is set): connect
   the provider, start a REINDEX, wait for the port and the swap, check the
   current settings and index name, and check that pure vector search
   (``hybrid_alpha=1.0``) finds each seeded document in the top 3 for a
   paraphrased query.
"""

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from onyx.db.enums import SwitchoverType
from onyx.error_handling.error_codes import OnyxErrorCode
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.embedding_models import (
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelSpec,
    EmbeddingModelStatus,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider
from shared_configs.utils import clean_model_name
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.reindex_port import ReindexPortManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestCCPair,
    DATestUser,
)
from tests.manual.embedding_models.provider_env import (
    provider_api_key,
    provider_env_name,
)
from tests.manual.gates import (
    EMBEDDING_E2E_GATE,
    EMBEDDING_E2E_MUTATION_GATE,
    env_flag,
    manual_suite,
)

pytestmark = [
    *manual_suite(EMBEDDING_E2E_GATE, EMBEDDING_E2E_MUTATION_GATE),
    pytest.mark.slow,
]

# Comma-separated exact model names, run in the given order. The last one
# stays PRESENT when the suite ends.
MODELS_ENV = "ONYX_EMBEDDING_E2E_MODELS"
# Overrides the per-model wait for the port and the swap, in seconds.
TIMEOUT_ENV = "ONYX_EMBEDDING_E2E_TIMEOUT_SECONDS"
# By default a failed or timed-out switch cancels its re-index, so a slow model
# does not keep the stack busy. Set to true to keep it for debugging.
KEEP_FAILED_REINDEX_ENV = "ONYX_EMBEDDING_E2E_KEEP_FAILED_REINDEX"
# A re-index must consent to deleting the connectors that it does not port
# (INVALID status). Without this opt-in, the suite refuses to give that consent.
ALLOW_CONNECTOR_DELETION_ENV = "ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION"

SEARCH_SETTINGS_URL = f"{API_SERVER_URL}/search-settings"
EMBEDDING_PROVIDER_URL = f"{API_SERVER_URL}/admin/embedding/embedding-provider"
# EE endpoint; the only search API that takes hybrid_alpha.
SEARCH_URL = f"{API_SERVER_URL}/search/send-search-message"

# The server may probe a cloud provider before it accepts a new target.
SET_SETTINGS_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
# The first query after a swap can load (or download) the model on the
# inference model server.
SEARCH_TIMEOUT = httpx.Timeout(900.0, connect=10.0)

DEFAULT_TIMEOUT_GPU_RECOMMENDED_SECONDS = 3600.0
DEFAULT_TIMEOUT_SELF_HOSTED_SECONDS = 1800.0
DEFAULT_TIMEOUT_CLOUD_SECONDS = 900.0
POLL_SECONDS = 10.0
PROGRESS_REPORT_SECONDS = 60.0
SEARCH_SETTLE_SECONDS = 60.0

TOP_K = 3
SEARCH_NUM_HITS = 10


@dataclass(frozen=True)
class _Fact:
    key: str
    content: str
    # A paraphrase with little word overlap, so only the vectors can match it.
    query: str


FACTS: tuple[_Fact, ...] = (
    _Fact(
        key="halvorsen-wrist-straps",
        content="Employees of the Halvorsen Robotics lab must wear anti-static "
        "wrist straps whenever they handle the prototype circuit boards.",
        query="What protective gear does Halvorsen Robotics require when staff "
        "touch unfinished electronics?",
    ),
    _Fact(
        key="pinecrest-rainwater",
        content="The Pinecrest community garden waters its tomato beds with "
        "rainwater collected in three large barrels behind the tool shed.",
        query="How are the vegetable plots at Pinecrest irrigated?",
    ),
    _Fact(
        key="ostrander-lunch",
        content="At Ostrander Middle School, students who forget their lunch can "
        "get a free sandwich from the front office before noon.",
        query="What happens at Ostrander if a pupil leaves the midday meal at home?",
    ),
    _Fact(
        key="vellmar-ferry-wind",
        content="The Vellmar ferry stops running across the bay whenever wind "
        "speeds exceed forty knots.",
        query="When is the Vellmar boat service suspended because of the weather?",
    ),
    _Fact(
        key="kestrel-home-office",
        content="Kestrel Analytics reimburses staff for up to two hundred dollars "
        "of home office furniture each calendar year.",
        query="How much can Kestrel Analytics workers claim back each year for "
        "desks and chairs they buy for remote work?",
    ),
)


@dataclass(frozen=True)
class _SeededDoc:
    document_id: str
    fact: _Fact


def _requested_target_names() -> list[str]:
    raw = os.environ.get(MODELS_ENV, "")
    return [name.strip() for name in raw.split(",") if name.strip()]


REQUESTED_TARGET_NAMES = _requested_target_names()
TARGET_NAMES: list[str] = REQUESTED_TARGET_NAMES or [
    spec.model_name for spec in selectable_embedding_model_specs()
]
LEGACY_SPECS: tuple[EmbeddingModelSpec, ...] = tuple(
    spec for spec in EMBEDDING_MODEL_SPECS if spec.status == EmbeddingModelStatus.LEGACY
)


def _short_name(model_name: str) -> str:
    return model_name.split("/")[-1]


def _legacy_id(spec: EmbeddingModelSpec) -> str:
    provider = spec.provider_type.value if spec.provider_type else "self-hosted"
    return f"{provider}-{_short_name(spec.model_name)}"


def _provider_value(spec: EmbeddingModelSpec) -> str | None:
    return spec.provider_type.value if spec.provider_type is not None else None


def _match_key(provider_type: str | None, model_name: str) -> tuple[str | None, str]:
    return provider_type, clean_model_name(model_name.strip())


def _resolve_target(model_name: str) -> EmbeddingModelSpec:
    for spec in selectable_embedding_model_specs():
        if spec.model_name == model_name:
            return spec
    names = ", ".join(spec.model_name for spec in selectable_embedding_model_specs())
    pytest.fail(
        f"{MODELS_ENV} names {model_name!r}, which is not a SELECTABLE model. "
        f"Use exact names from: {names}"
    )


def _timeout_for(spec: EmbeddingModelSpec) -> float:
    override = os.environ.get(TIMEOUT_ENV, "").strip()
    if override:
        return float(override)
    if spec.provider_type is not None:
        return DEFAULT_TIMEOUT_CLOUD_SECONDS
    if spec.gpu_recommended:
        return DEFAULT_TIMEOUT_GPU_RECOMMENDED_SECONDS
    return DEFAULT_TIMEOUT_SELF_HOSTED_SECONDS


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error_code = body.get("error_code")
    return error_code if isinstance(error_code, str) else None


def _require_no_reindex_in_progress(admin: DATestUser) -> None:
    secondary = ReindexPortManager.get_secondary_settings(admin)
    if secondary is not None:
        pytest.fail(
            f"A re-index to {secondary['model_name']} is already in progress on "
            f"{API_SERVER_URL}. Let it finish, or cancel it on the admin Index "
            "Settings page, then run the suite again."
        )


def _provider_is_configured(provider: EmbeddingProvider, admin: DATestUser) -> bool:
    response: httpx.Response = client.get(
        f"{EMBEDDING_PROVIDER_URL}/{provider.value}", headers=admin.headers
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def _connect_provider(
    provider: EmbeddingProvider, api_key: str, admin: DATestUser
) -> None:
    response: httpx.Response = client.put(
        EMBEDDING_PROVIDER_URL,
        json={
            "provider_type": provider.value,
            "api_key": api_key,
            "api_key_changed": True,
        },
        headers=admin.headers,
    )
    if not response.is_success:
        pytest.fail(
            f"Could not save the {provider.value} embedding provider: "
            f"HTTP {response.status_code} {response.text}"
        )


def _consented_connector_deletions(admin: DATestUser) -> list[int]:
    """The cc_pairs (INVALID status) that a re-index must consent to delete.

    Fails if there are any and the operator did not opt in. Read again before
    each re-index, because a connector can turn INVALID during the run."""
    wont_port_cc_pair_ids = ReindexPortManager.wont_port_cc_pair_ids(admin)
    if wont_port_cc_pair_ids and not env_flag(ALLOW_CONNECTOR_DELETION_ENV):
        pytest.fail(
            f"The connectors (cc_pairs) {wont_port_cc_pair_ids} are INVALID. A "
            "re-index consents to deleting them, and the clean-up after the "
            "swap deletes them and their documents. Fix or delete them first, "
            f"or set {ALLOW_CONNECTOR_DELETION_ENV}=true."
        )
    return wont_port_cc_pair_ids


def _reindex_payload(spec: EmbeddingModelSpec, admin: DATestUser) -> dict[str, Any]:
    """A set-new-search-settings body for ``spec`` that keeps the other settings.

    Fails before any request if the re-index would delete connectors and the
    operator did not opt in."""
    wont_port_cc_pair_ids = _consented_connector_deletions(admin)
    current = ReindexPortManager.get_current_settings(admin)
    payload: dict[str, Any] = {
        "model_name": spec.model_name,
        "model_dim": spec.model_dim,
        "normalize": spec.normalize,
        "query_prefix": spec.query_prefix,
        "passage_prefix": spec.passage_prefix,
        "provider_type": _provider_value(spec),
        "index_name": None,
        "multipass_indexing": current.get("multipass_indexing", False),
        "reduced_dimension": None,
        "switchover_type": SwitchoverType.REINDEX.value,
        "enable_contextual_rag": current.get("enable_contextual_rag", False),
        "contextual_rag_model_configuration_id": current.get(
            "contextual_rag_model_configuration_id"
        ),
        "acknowledged_wont_port_cc_pair_ids": wont_port_cc_pair_ids,
    }
    if current.get("vector_quantization") is not None:
        payload["vector_quantization"] = current["vector_quantization"]
    return payload


def _post_new_search_settings(
    payload: dict[str, Any], admin: DATestUser
) -> httpx.Response:
    return client.post(
        f"{SEARCH_SETTINGS_URL}/set-new-search-settings",
        json=payload,
        headers=admin.headers,
        timeout=SET_SETTINGS_TIMEOUT,
    )


def _start_reindex_to(
    spec: EmbeddingModelSpec, admin: DATestUser, timeout: float
) -> int:
    """Start the re-index. Retry while an earlier index of the same name drains."""
    deadline = time.monotonic() + timeout
    while True:
        response = _post_new_search_settings(_reindex_payload(spec, admin), admin)
        if (
            response.status_code == 409
            and _error_code(response) == OnyxErrorCode.INDEX_NAME_RECLAIMING.code
            and time.monotonic() < deadline
        ):
            print("The index name is still being reclaimed; retrying in 5s.")
            time.sleep(5)
            continue
        if not response.is_success:
            pytest.fail(
                f"set-new-search-settings refused {spec.model_name}: "
                f"HTTP {response.status_code} {response.text}"
            )
        return int(response.json()["id"])


def _wait_for_swap(
    original_index_name: str, admin: DATestUser, timeout: float
) -> dict[str, Any]:
    """Poll until the new index is PRESENT. Fail on a paused port or on timeout.

    A FAILED port unit retries on its own, so it only fails the test at the
    timeout. A PAUSED unit waits for an operator, so it fails at once.
    """
    start = time.monotonic()
    last_report = 0.0
    while True:
        current = ReindexPortManager.get_current_settings(admin)
        if current["index_name"] != original_index_name:
            return current

        progress = ReindexPortManager.get_progress(admin)
        if progress.paused:
            errors = ReindexPortManager.get_errors(admin)
            pytest.fail(f"The re-index port paused: {progress}; errors: {errors}")

        if ReindexPortManager.get_secondary_settings(admin) is None:
            current = ReindexPortManager.get_current_settings(admin)
            if current["index_name"] != original_index_name:
                return current
            pytest.fail("The re-index disappeared before the swap (cancelled?).")

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            errors = ReindexPortManager.get_errors(admin)
            pytest.fail(
                f"No swap within {timeout:.0f}s. Last progress: {progress}; "
                f"errors: {errors}. Raise {TIMEOUT_ENV} for slow models "
                "(for example Nemotron on CPU)."
            )
        if elapsed - last_report >= PROGRESS_REPORT_SECONDS:
            print(f"Waiting for the swap: {progress} elapsed={elapsed:.0f}s")
            last_report = elapsed
        time.sleep(POLL_SECONDS)


def _cancel_after_failure(admin: DATestUser) -> None:
    if env_flag(KEEP_FAILED_REINDEX_ENV):
        print(f"{KEEP_FAILED_REINDEX_ENV} is set; leaving the re-index running.")
        return
    try:
        if ReindexPortManager.get_secondary_settings(admin) is not None:
            ReindexPortManager.cancel_reindex(admin)
            print("Cancelled the unfinished re-index.")
    except Exception as e:
        print(f"Could not cancel the unfinished re-index: {e!r}")


def _search_document_ids(query: str, admin: DATestUser) -> list[str]:
    """Document ids for a pure vector search, best first, one entry per document."""
    response: httpx.Response = client.post(
        SEARCH_URL,
        json={
            "search_query": query,
            "hybrid_alpha": 1.0,
            "num_hits": SEARCH_NUM_HITS,
            "run_query_expansion": False,
            "include_content": False,
            "stream": False,
        },
        headers=admin.headers,
        timeout=SEARCH_TIMEOUT,
    )
    if response.status_code == 404:
        pytest.fail(
            f"{SEARCH_URL} returned 404. This suite needs the EE search API; start "
            "the stack with ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true."
        )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        pytest.fail(f"Search failed: {body['error']}")
    document_ids: list[str] = []
    for doc in body.get("search_docs", []):
        document_id = doc["document_id"]
        if document_id not in document_ids:
            document_ids.append(document_id)
    return document_ids


def _retrieval_misses(docs: list[_SeededDoc], admin: DATestUser) -> list[str]:
    misses: list[str] = []
    for doc in docs:
        top = _search_document_ids(doc.fact.query, admin)[:TOP_K]
        if doc.document_id not in top:
            misses.append(f"{doc.fact.query!r}: expected {doc.document_id}, got {top}")
    return misses


def _assert_seeded_docs_retrievable(
    docs: list[_SeededDoc], admin: DATestUser, model_name: str
) -> None:
    deadline = time.monotonic() + SEARCH_SETTLE_SECONDS
    misses = _retrieval_misses(docs, admin)
    while misses and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        misses = _retrieval_misses(docs, admin)
    assert not misses, (
        f"Pure vector search with {model_name} missed seeded documents in the "
        f"top {TOP_K}:\n" + "\n".join(misses)
    )


def _assert_current_settings(current: dict[str, Any], spec: EmbeddingModelSpec) -> None:
    assert current["model_name"] == spec.model_name
    assert current["model_dim"] == spec.model_dim
    assert current.get("provider_type") == _provider_value(spec)
    assert current["normalize"] == spec.normalize
    assert (current.get("query_prefix") or "") == spec.query_prefix
    assert (current.get("passage_prefix") or "") == spec.passage_prefix
    assert current.get("reduced_dimension") is None
    base_index_name = f"danswer_chunk_{clean_model_name(spec.model_name)}"
    assert current["index_name"] in (
        base_index_name,
        base_index_name + ALT_INDEX_SUFFIX,
    ), f"unexpected index name {current['index_name']}"


@pytest.fixture(scope="module", autouse=True)
def _connector_deletion_check(
    _live_api_server: None,  # noqa: ARG001
    e2e_admin: DATestUser,
) -> None:
    """Stop before the first change (seeded documents, provider keys, any
    re-index) if a re-index would delete connectors without the opt-in."""
    _consented_connector_deletions(e2e_admin)


@pytest.fixture(scope="module")
def seeded_docs(
    e2e_admin: DATestUser,
    e2e_api_key: DATestAPIKey,
    e2e_cc_pair: DATestCCPair,
    e2e_marker: str,
) -> list[_SeededDoc]:
    """Seed the facts once. Each switch re-embeds them through the port flow."""
    docs: list[_SeededDoc] = []
    for fact in FACTS:
        document_id = f"embedding-e2e-{e2e_marker}-{fact.key}"
        DocumentManager.seed_doc_with_content(
            e2e_cc_pair, fact.content, e2e_api_key, document_id=document_id
        )
        docs.append(_SeededDoc(document_id=document_id, fact=fact))
    # Fails here, before any settings change, if the search API is missing.
    _search_document_ids(FACTS[0].query, e2e_admin)
    return docs


@pytest.mark.parametrize("legacy_spec", LEGACY_SPECS, ids=_legacy_id)
def test_legacy_target_is_rejected(
    legacy_spec: EmbeddingModelSpec, e2e_admin: DATestUser
) -> None:
    _require_no_reindex_in_progress(e2e_admin)
    current = ReindexPortManager.get_current_settings(e2e_admin)
    if _match_key(current.get("provider_type"), current["model_name"]) == _match_key(
        _provider_value(legacy_spec), legacy_spec.model_name
    ):
        pytest.skip("This legacy model is PRESENT; a same-model re-index is allowed.")

    response = _post_new_search_settings(
        _reindex_payload(legacy_spec, e2e_admin), e2e_admin
    )
    if response.is_success:
        ReindexPortManager.cancel_reindex(e2e_admin)
        pytest.fail(
            f"The server accepted the LEGACY target {legacy_spec.model_name}, so the "
            "upgrade-only guard is missing. The new re-index was cancelled."
        )
    assert 400 <= response.status_code < 500, (
        f"HTTP {response.status_code} {response.text}"
    )
    # Without a configured provider the older "no embedding provider" check
    # answers first, which is also a 4xx. Otherwise the guard must answer.
    provider = legacy_spec.provider_type
    if provider is None or _provider_is_configured(provider, e2e_admin):
        assert _error_code(response) == OnyxErrorCode.INVALID_INPUT.code, (
            f"HTTP {response.status_code} {response.text}"
        )


def test_same_model_reindex_is_accepted_then_cancelled(
    e2e_admin: DATestUser,
) -> None:
    _require_no_reindex_in_progress(e2e_admin)
    before = ReindexPortManager.get_current_settings(e2e_admin)

    # Explicit consent: the helper's default consents to deleting every INVALID
    # connector, and a small stack can swap before the cancel below.
    ReindexPortManager.wait_for_reindex_accepted(
        e2e_admin,
        acknowledged_wont_port_cc_pair_ids=_consented_connector_deletions(e2e_admin),
    )
    try:
        secondary = ReindexPortManager.get_secondary_settings(e2e_admin)
        if secondary is not None:
            assert secondary["model_name"] == before["model_name"]
    finally:
        ReindexPortManager.cancel_reindex(e2e_admin)

    assert ReindexPortManager.get_secondary_settings(e2e_admin) is None
    after = ReindexPortManager.get_current_settings(e2e_admin)
    assert after["model_name"] == before["model_name"]
    assert after.get("provider_type") == before.get("provider_type")


@pytest.mark.parametrize("target_name", TARGET_NAMES, ids=_short_name)
def test_switch_to_model(
    target_name: str,
    e2e_admin: DATestUser,
    seeded_docs: list[_SeededDoc],
) -> None:
    spec = _resolve_target(target_name)
    provider = spec.provider_type
    if provider is not None:
        api_key = provider_api_key(provider)
        if api_key is None:
            message = f"{provider_env_name(provider)} is not set."
            if REQUESTED_TARGET_NAMES:
                pytest.fail(f"{MODELS_ENV} selects {spec.model_name}, but {message}")
            pytest.skip(message)
        _require_no_reindex_in_progress(e2e_admin)
        _connect_provider(provider, api_key, e2e_admin)
    else:
        _require_no_reindex_in_progress(e2e_admin)

    timeout = _timeout_for(spec)
    original = ReindexPortManager.get_current_settings(e2e_admin)
    print(
        f"Switching {original['model_name']} ({original['index_name']}) to "
        f"{spec.model_name}; timeout {timeout:.0f}s"
    )
    _start_reindex_to(spec, e2e_admin, timeout)
    try:
        current = _wait_for_swap(original["index_name"], e2e_admin, timeout)
    except BaseException:
        _cancel_after_failure(e2e_admin)
        raise

    _assert_current_settings(current, spec)
    _assert_seeded_docs_retrievable(seeded_docs, e2e_admin, spec.model_name)
