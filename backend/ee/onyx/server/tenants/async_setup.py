import asyncio
import logging

from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import ANTHROPIC_DEFAULT_API_KEY
from ee.onyx.configs.app_configs import COHERE_DEFAULT_API_KEY
from ee.onyx.configs.app_configs import OPENAI_DEFAULT_API_KEY
from ee.onyx.server.tenants.schema_management import run_alembic_migrations
from onyx.configs.constants import MilestoneRecordType
from onyx.db.engine import get_session_with_tenant
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_cloud_embedding_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import IndexModelStatus
from onyx.db.models import SearchSettings
from onyx.llm.llm_provider_options import ANTHROPIC_MODEL_NAMES
from onyx.llm.llm_provider_options import ANTHROPIC_PROVIDER_NAME
from onyx.llm.llm_provider_options import OPEN_AI_MODEL_NAMES
from onyx.llm.llm_provider_options import OPENAI_PROVIDER_NAME
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.setup import setup_onyx
from onyx.utils.telemetry import create_milestone_and_report
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.enums import EmbeddingProvider

logger = logging.getLogger(__name__)


async def complete_tenant_setup(tenant_id: str, email: str) -> None:
    """
    Complete the tenant setup process asynchronously after the essential migrations
    have been applied. This includes:
    1. Running the remaining Alembic migrations
    2. Setting up Onyx
    3. Creating milestone records
    """
    logger.info(f"Starting asynchronous tenant setup for tenant {tenant_id}")
    token = None

    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

        # Run the remaining Alembic migrations
        await asyncio.to_thread(run_alembic_migrations, tenant_id)

        # Configure default API keys
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            configure_default_api_keys(db_session)

        # Setup Onyx
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            current_search_settings = (
                db_session.query(SearchSettings)
                .filter_by(status=IndexModelStatus.FUTURE)
                .first()
            )
            cohere_enabled = (
                current_search_settings is not None
                and current_search_settings.provider_type == EmbeddingProvider.COHERE
            )
            setup_onyx(db_session, tenant_id, cohere_enabled=cohere_enabled)

        # Create milestone record
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            create_milestone_and_report(
                user=None,
                distinct_id=tenant_id,
                event_type=MilestoneRecordType.TENANT_CREATED,
                properties={
                    "email": email,
                },
                db_session=db_session,
            )

        logger.info(f"Asynchronous tenant setup completed for tenant {tenant_id}")

    except Exception as e:
        logger.exception(
            f"Failed to complete asynchronous tenant setup for tenant {tenant_id}: {e}"
        )
    finally:
        if token is not None:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def configure_default_api_keys(db_session: Session) -> None:
    if ANTHROPIC_DEFAULT_API_KEY:
        anthropic_provider = LLMProviderUpsertRequest(
            name="Anthropic",
            provider=ANTHROPIC_PROVIDER_NAME,
            api_key=ANTHROPIC_DEFAULT_API_KEY,
            default_model_name="claude-3-7-sonnet-20250219",
            fast_default_model_name="claude-3-5-sonnet-20241022",
            model_names=ANTHROPIC_MODEL_NAMES,
            display_model_names=["claude-3-5-sonnet-20241022"],
        )
        try:
            full_provider = upsert_llm_provider(anthropic_provider, db_session)
            update_default_provider(full_provider.id, db_session)
        except Exception as e:
            logger.error(f"Failed to configure Anthropic provider: {e}")
    else:
        logger.error(
            "ANTHROPIC_DEFAULT_API_KEY not set, skipping Anthropic provider configuration"
        )

    if OPENAI_DEFAULT_API_KEY:
        open_provider = LLMProviderUpsertRequest(
            name="OpenAI",
            provider=OPENAI_PROVIDER_NAME,
            api_key=OPENAI_DEFAULT_API_KEY,
            default_model_name="gpt-4o",
            fast_default_model_name="gpt-4o-mini",
            model_names=OPEN_AI_MODEL_NAMES,
            display_model_names=["o1", "o3-mini", "gpt-4o", "gpt-4o-mini"],
        )
        try:
            full_provider = upsert_llm_provider(open_provider, db_session)
            update_default_provider(full_provider.id, db_session)
        except Exception as e:
            logger.error(f"Failed to configure OpenAI provider: {e}")
    else:
        logger.error(
            "OPENAI_DEFAULT_API_KEY not set, skipping OpenAI provider configuration"
        )

    if COHERE_DEFAULT_API_KEY:
        cloud_embedding_provider = CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.COHERE,
            api_key=COHERE_DEFAULT_API_KEY,
        )

        try:
            logger.info("Attempting to upsert Cohere cloud embedding provider")
            upsert_cloud_embedding_provider(cloud_embedding_provider, db_session)
        except Exception as e:
            logger.error(f"Failed to configure Cohere provider: {e}")
    else:
        logger.error(
            "COHERE_DEFAULT_API_KEY not set, skipping Cohere provider configuration"
        )
