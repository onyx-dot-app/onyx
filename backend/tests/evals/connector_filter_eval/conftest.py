import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import fetch_llm_provider_view
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest

# This suite lives outside tests/external_dependency_unit (so the EDU CI
# matrix doesn't discover it) but runs against the same live dependencies,
# so it reuses that tree's fixtures via explicit imports.
from tests.external_dependency_unit.answer.conftest import (  # noqa: F401
    mock_external_deps,
)
from tests.external_dependency_unit.answer.conftest import mock_file_store  # noqa: F401
from tests.external_dependency_unit.answer.conftest import mock_gpu_status  # noqa: F401
from tests.external_dependency_unit.answer.conftest import (  # noqa: F401
    mock_nlp_embeddings_post,
)
from tests.external_dependency_unit.answer.conftest import (  # noqa: F401
    mock_vespa_query,
)
from tests.external_dependency_unit.conftest import db_session  # noqa: F401
from tests.external_dependency_unit.conftest import full_deployment_setup  # noqa: F401

# This suite makes real LLM calls, so it is disabled by default and only runs
# when explicitly opted in.
_RUN_FLAG_ENV = "RUN_CONNECTOR_FILTER_EVAL"
_PACKAGE_DIR = Path(__file__).parent

# Provider auto-provisioned (from OPENAI_API_KEY) when the database has none,
# so the eval can run against a fresh CI database. Cheap tier per repo policy.
_FALLBACK_PROVIDER_NAME = "connector-filter-eval"
_FALLBACK_MODEL = "gpt-5-mini"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get(_RUN_FLAG_ENV):
        return
    skip = pytest.mark.skip(reason=f"manual-only eval; set {_RUN_FLAG_ENV}=1 to run")
    for item in items:
        if _PACKAGE_DIR in item.path.parents:
            item.add_marker(skip)


def _ensure_llm_provider(db_session: Session) -> None:  # noqa: F811
    """Create a default OpenAI provider from OPENAI_API_KEY if none exists."""
    if fetch_existing_llm_providers(db_session, [LLMModelFlowType.CHAT]):
        return
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return
    provider = upsert_llm_provider(
        llm_provider_upsert_request=LLMProviderUpsertRequest(
            name=_FALLBACK_PROVIDER_NAME,
            provider=LlmProviderNames.OPENAI,
            api_key=api_key,
            is_public=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(name=_FALLBACK_MODEL, is_visible=True)
            ],
            groups=[],
        ),
        db_session=db_session,
    )
    update_default_provider(provider.id, _FALLBACK_MODEL, db_session)
    db_session.commit()


@pytest.fixture
def eval_llm(
    db_session: Session,  # noqa: F811
    full_deployment_setup: None,  # noqa: ARG001, F811
    mock_external_deps: None,  # noqa: ARG001, F811
) -> LLM:
    """The LLM the eval runs against. Honors the EVAL_LLM_* env vars so the
    cheap tier is used; falls back to the tenant default provider, creating one
    from OPENAI_API_KEY when the database has none (fresh CI database)."""
    provider_name = os.environ.get("EVAL_LLM_PROVIDER")
    model = os.environ.get("EVAL_LLM_MODEL")
    if provider_name and model:
        view = fetch_llm_provider_view(db_session, provider_name)
        if view is None:
            pytest.skip(f"EVAL_LLM_PROVIDER {provider_name!r} not configured")
        return llm_from_provider(model_name=model, llm_provider=view)
    _ensure_llm_provider(db_session)
    if not fetch_existing_llm_providers(db_session, [LLMModelFlowType.CHAT]):
        pytest.skip("no LLM provider configured; set one up to run the eval")
    return get_default_llm()
