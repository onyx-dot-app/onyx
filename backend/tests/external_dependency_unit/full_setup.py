from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import nltk  # type: ignore

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_active_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.models import IndexingSetting
from onyx.setup import setup_postgres
from onyx.setup import setup_vespa
from shared_configs import configs as shared_configs_module
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


_SETUP_COMPLETE: bool = False


def ensure_full_deployment_setup(
    tenant_id: Optional[str] = None,
) -> None:
    """Initialize test environment to mirror a real deployment, on demand.

    - Initializes DB engine and sets tenant context
    - Skips model warm-ups during setup
    - Runs setup_onyx (Postgres defaults, Vespa indices)
    - Initializes file store (best-effort)
    - Ensures Vespa indices exist
    - Installs NLTK stopwords and punkt_tab
    """
    global _SETUP_COMPLETE
    if _SETUP_COMPLETE:
        return

    if os.environ.get("SKIP_EXTERNAL_DEPENDENCY_UNIT_SETUP", "").lower() == "true":
        return

    tenant = tenant_id or TEST_TENANT_ID

    # Initialize engine (noop if already initialized)
    SqlEngine.init_engine(pool_size=10, max_overflow=5)

    # Avoid warm-up network calls during setup
    shared_configs_module.SKIP_WARM_UP = True

    nltk.download("stopwords", quiet=True)
    nltk.download("punkt_tab", quiet=True)

    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    original_cwd = os.getcwd()
    backend_dir = Path(__file__).resolve().parents[2]  # points to 'backend'
    os.chdir(str(backend_dir))

    try:
        with get_session_with_current_tenant() as db_session:
            setup_postgres(db_session)

            # Initialize file store; ignore if not configured
            try:
                get_default_file_store().initialize()
            except Exception:
                pass

        # Also ensure indices exist explicitly (no-op if already created)
        with get_session_with_current_tenant() as db_session:
            active = get_active_search_settings(db_session)
            document_index = get_default_document_index(
                active.primary, active.secondary
            )
            ok = setup_vespa(
                document_index=document_index,
                index_setting=IndexingSetting.from_db_model(active.primary),
                secondary_index_setting=(
                    IndexingSetting.from_db_model(active.secondary)
                    if active.secondary
                    else None
                ),
            )
            if not ok:
                raise RuntimeError(
                    "Vespa did not initialize within the specified timeout."
                )

        _SETUP_COMPLETE = True
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        os.chdir(original_cwd)
