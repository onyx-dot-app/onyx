import asyncio
import hashlib
import time
import uuid

import aiohttp  # Async HTTP client
import httpx
import requests
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import HUBSPOT_TRACKING_URL
from ee.onyx.db.available_tenant import take_available_tenant
from ee.onyx.db.user_tenant_mapping import (
    add_users_to_tenant,
    resolve_tenant_id,
    user_owns_a_tenant,
)
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.models import (
    PoolTenant,
    TenantByDomainResponse,
    TenantCreationPayload,
    TenantDeletionPayload,
)
from ee.onyx.server.tenants.schema_management import (
    create_schema_if_not_exists,
    drop_schema,
    get_alembic_head_revision,
    run_alembic_migrations,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import (
    ANTHROPIC_DEFAULT_API_KEY,
    AUTO_PROVISION_DEFAULT_LLM_PROVIDERS,
    COHERE_DEFAULT_API_KEY,
    CONTROL_PLANE_API_BASE_URL,
    DEV_MODE,
    OPENAI_DEFAULT_API_KEY,
    OPENROUTER_DEFAULT_API_KEY,
    TENANT_PROVISIONING_WAIT_SECONDS,
    VERTEXAI_DEFAULT_CREDENTIALS,
    VERTEXAI_DEFAULT_LOCATION,
)
from onyx.configs.constants import (
    ONYX_CLOUD_PROVISION_FAILURE_KEY_PREFIX,
    ONYX_CLOUD_TENANT_ID,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.shard_routing import get_shard_for_new_tenant
from onyx.db.engine.sql_engine import (
    get_session_with_shared_schema,
    get_session_with_tenant,
)
from onyx.db.image_generation import create_default_image_gen_config_from_api_key
from onyx.db.llm import (
    fetch_existing_llm_provider_by_name_and_type,
    fetch_existing_llm_provider_by_type_nameless,
    update_default_provider,
    upsert_cloud_embedding_provider,
    upsert_llm_provider,
)
from onyx.db.models import (
    AvailableTenant,
    IndexModelStatus,
    SearchSettings,
    UserTenantMapping,
)
from onyx.db.tenant_shard import clear_tenant_placement, record_tenant_placement
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.constants import (
    ANTHROPIC_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
    OPENROUTER_PROVIDER_NAME,
    VERTEX_CREDENTIALS_FILE_KWARG,
    VERTEX_LOCATION_KWARG,
    VERTEXAI_PROVIDER_NAME,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    get_recommendations,
    model_configurations_for_provider,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.setup import setup_onyx
from onyx.utils.logger import setup_logger
from shared_configs.configs import (
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    TENANT_ID_PREFIX,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.enums import EmbeddingProvider

logger = setup_logger()

# Matches billing.py. Without it a hung control plane pins the caller forever.
_CONTROL_PLANE_TIMEOUT_S = 30

# A signup polls for its worker-built tenant at this interval.
_PROVISIONING_POLL_INTERVAL_S = 1.0

# Covers a pool assignment plus the control plane call (30s timeout).
_REQUEST_PROVISION_LOCK_TIMEOUT_S = 60


async def get_or_provision_tenant(
    email: str,
    referral_source: str | None = None,
    request: Request | None = None,
    oauth_name: str | None = None,
    account_id: str | None = None,
) -> str:
    """
    Get existing tenant ID for an email or create a new tenant if none exists.
    This function should only be called after we have verified we want this user's tenant to exist.
    It returns the tenant ID associated with the email, creating a new tenant if necessary.

    When the caller knows the IdP subject it is tried before the email, which is
    what stops a renamed user being treated as a brand new signup.

    Alembic never runs in the api server. A pool tenant that is already at the
    code's head revision is assigned here. Anything that needs a migration is
    built by a worker while this request waits for the mapping to appear.
    """
    # Early return for non-multi-tenant mode
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    if referral_source and request:
        await submit_to_hubspot(email, referral_source, request)

    tenant_id = resolve_tenant_id(email, oauth_name, account_id)
    if tenant_id:
        return tenant_id

    # The same lock the worker task takes. Two overlapping signups for one
    # email (a double submit, two tabs) must not each take a pool tenant.
    lock = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID).lock(
        user_provision_lock_name(email), timeout=_REQUEST_PROVISION_LOCK_TIMEOUT_S
    )
    if not lock.acquire(blocking=False):
        return await _wait_for_tenant(email, oauth_name, account_id)

    try:
        pool_tenant = await get_available_tenant()
        if pool_tenant is not None:
            await finish_tenant_assignment(
                pool_tenant.tenant_id, email, referral_source
            )
            return pool_tenant.tenant_id
    except Exception as e:
        logger.error("Failed to provision tenant", exc_info=e)
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Failed to provision tenant. Please try again later.",
        )
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Could not release the signup lock (likely expired)")

    _enqueue_user_provisioning(email, referral_source)
    return await _wait_for_tenant(email, oauth_name, account_id)


def _email_digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def user_provision_lock_name(email: str) -> str:
    return f"{OnyxRedisLocks.CLOUD_PROVISION_TENANT_FOR_USER_LOCK_PREFIX}:{_email_digest(email)}"


def user_provision_failure_key(email: str) -> str:
    """Set by the worker when a signup's provisioning fails, so the waiting
    request fails now instead of polling until its deadline."""
    return f"{ONYX_CLOUD_PROVISION_FAILURE_KEY_PREFIX}:{_email_digest(email)}"


async def finish_tenant_assignment(
    tenant_id: str, email: str, referral_source: str | None
) -> None:
    """Tell the control plane, then write the mapping that makes the tenant
    visible to the user. In this order a failed notification never leaves a
    workspace the user can log in to but billing has never heard of. On
    failure both planes are rolled back, since the tenant is already out of
    the pool."""
    control_plane_notified = False
    try:
        if not DEV_MODE:
            await notify_control_plane(tenant_id, email, referral_source)
            control_plane_notified = True
        await assign_tenant_to_user(tenant_id, email, referral_source)
    except Exception:
        logger.exception("Failed to assign tenant %s, rolling it back", tenant_id)
        if control_plane_notified:
            try:
                await delete_user_from_control_plane(tenant_id, email)
            except Exception:
                logger.exception(
                    "Failed to remove tenant %s from the control plane", tenant_id
                )
        try:
            await rollback_tenant_provisioning(tenant_id)
        except Exception:
            logger.exception("Failed to rollback tenant %s", tenant_id)
        raise
    logger.info("Assigned tenant %s to user %s", tenant_id, email)


def _enqueue_user_provisioning(email: str, referral_source: str | None) -> None:
    # A retry after a failed attempt starts from a clean marker.
    get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID).delete(
        user_provision_failure_key(email)
    )
    client_app.send_task(
        OnyxCeleryTask.CLOUD_PROVISION_TENANT_FOR_USER,
        kwargs={
            "tenant_id": ONYX_CLOUD_TENANT_ID,
            "email": email,
            "referral_source": referral_source,
        },
        queue=OnyxCeleryQueues.MONITORING,
        priority=OnyxCeleryPriority.HIGH,
        # Past this the request has already failed, so the user retries and
        # enqueues again. Running the stale task too would build twice.
        expires=TENANT_PROVISIONING_WAIT_SECONDS,
    )


async def _wait_for_tenant(
    email: str, oauth_name: str | None, account_id: str | None
) -> str:
    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    failure_key = user_provision_failure_key(email)
    deadline = time.monotonic() + TENANT_PROVISIONING_WAIT_SECONDS
    while time.monotonic() < deadline:
        tenant_id = resolve_tenant_id(email, oauth_name, account_id)
        if tenant_id:
            return tenant_id
        if redis_client.get(failure_key) is not None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Failed to provision tenant. Please try again later.",
            )
        await asyncio.sleep(_PROVISIONING_POLL_INTERVAL_S)
    logger.warning("Timed out waiting for tenant provisioning for user %s", email)
    raise OnyxError(
        OnyxErrorCode.SERVICE_UNAVAILABLE,
        "Your workspace is still being set up. Try again in a minute.",
    )


async def provision_user_tenant(email: str, referral_source: str | None) -> str:
    """Worker side of a signup that found no current pool tenant.

    Takes a stale pool tenant and migrates it, or builds a tenant from scratch,
    then assigns it and tells the control plane. Returns the tenant id.
    """
    tenant_id = resolve_tenant_id(email)
    if tenant_id:
        return tenant_id

    pool_tenant = await get_available_tenant(allow_stale=True)
    if pool_tenant is not None:
        tenant_id = pool_tenant.tenant_id
        if pool_tenant.alembic_version != get_alembic_head_revision():
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None, lambda: run_alembic_migrations(tenant_id)
                )
            except Exception:
                # The tenant was already dequeued from the pool. Roll it back so
                # it does not end up orphaned (schema exists, assigned to nobody).
                logger.exception(
                    "Migration failed for pre-provisioned tenant %s; rolling back",
                    tenant_id,
                )
                try:
                    await rollback_tenant_provisioning(tenant_id)
                except Exception:
                    logger.exception("Failed to rollback orphaned tenant %s", tenant_id)
                raise
    else:
        tenant_id = await create_tenant(email, referral_source)

    await finish_tenant_assignment(tenant_id, email, referral_source)
    return tenant_id


async def create_tenant(
    email: str,
    referral_source: str | None = None,  # noqa: ARG001
) -> str:
    """
    Create a new tenant on-demand when no pre-provisioned tenants are available.
    This is the fallback method when we can't use a pre-provisioned tenant.

    """
    tenant_id = TENANT_ID_PREFIX + str(uuid.uuid4())
    logger.info("Creating new tenant %s for user %s", tenant_id, email)

    try:
        # Provision tenant on data plane
        await provision_tenant(tenant_id, email)

    except Exception as e:
        logger.exception("Tenant provisioning failed: %s", str(e))
        # Attempt to rollback the tenant provisioning
        try:
            await rollback_tenant_provisioning(tenant_id)
        except Exception:
            logger.exception("Failed to rollback tenant provisioning for %s", tenant_id)
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Failed to provision tenant.")

    return tenant_id


async def provision_tenant(tenant_id: str, email: str) -> None:
    if not MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.DEPLOYMENT_UNSUPPORTED, "Multi-tenancy is not enabled"
        )

    if user_owns_a_tenant(email):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "User already belongs to an organization"
        )

    shard_name = get_shard_for_new_tenant()
    logger.debug(
        "Provisioning tenant %s for user %s on shard %s", tenant_id, email, shard_name
    )

    try:
        # Before schema creation: every step below routes via the catalog.
        record_tenant_placement(tenant_id, shard_name)

        # Create the schema for the tenant
        if not create_schema_if_not_exists(tenant_id):
            logger.debug("Created schema for tenant %s", tenant_id)
        else:
            logger.debug("Schema already exists for tenant %s", tenant_id)

        # Set up the tenant with all necessary configurations. The caller
        # notifies the control plane and assigns the tenant afterwards.
        await setup_tenant(tenant_id)

    except Exception as e:
        logger.exception("Failed to create tenant %s", tenant_id)
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, f"Failed to create tenant: {str(e)}"
        )


async def notify_control_plane(
    tenant_id: str, email: str, referral_source: str | None = None
) -> None:
    logger.info("Fetching billing information")
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = TenantCreationPayload(
        tenant_id=tenant_id, email=email, referral_source=referral_source
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CONTROL_PLANE_API_BASE_URL}/tenants/create",
            headers=headers,
            json=payload.model_dump(),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error("Control plane tenant creation failed: %s", error_text)
                raise Exception(
                    f"Failed to create tenant on control plane: {error_text}"
                )


async def rollback_tenant_provisioning(tenant_id: str) -> None:
    """
    Logic to rollback tenant provisioning on data plane.
    Handles each step independently to ensure maximum cleanup even if some steps fail.
    """
    logger.info("Rolling back tenant provisioning for tenant_id: %s", tenant_id)

    # Track if any part of the rollback fails
    rollback_errors = []

    # 1. Try to drop the tenant's schema
    schema_dropped = False
    try:
        drop_schema(tenant_id)
        schema_dropped = True
        logger.info("Successfully dropped schema for tenant %s", tenant_id)
    except Exception as e:
        error_msg = f"Failed to drop schema for tenant {tenant_id}: {str(e)}"
        logger.error(error_msg)
        rollback_errors.append(error_msg)

    # 2. Try to remove tenant mapping
    try:
        with get_session_with_shared_schema() as db_session:
            db_session.begin()
            try:
                db_session.query(UserTenantMapping).filter(
                    UserTenantMapping.tenant_id == tenant_id
                ).delete()
                db_session.commit()
                logger.info(
                    "Successfully removed user mappings for tenant %s", tenant_id
                )
            except Exception as e:
                db_session.rollback()
                raise e
    except Exception as e:
        error_msg = f"Failed to remove user mappings for tenant {tenant_id}: {str(e)}"
        logger.error(error_msg)
        rollback_errors.append(error_msg)

    # 3. If this tenant was in the available tenants table, remove it
    try:
        with get_session_with_shared_schema() as db_session:
            db_session.begin()
            try:
                available_tenant = (
                    db_session.query(AvailableTenant)
                    .filter(AvailableTenant.tenant_id == tenant_id)
                    .first()
                )

                if available_tenant:
                    db_session.delete(available_tenant)
                    db_session.commit()
                    logger.info(
                        "Removed tenant %s from available tenants table", tenant_id
                    )
            except Exception as e:
                db_session.rollback()
                raise e
    except Exception as e:
        error_msg = f"Failed to remove tenant {tenant_id} from available tenants table: {str(e)}"
        logger.error(error_msg)
        rollback_errors.append(error_msg)

    # 4. Drop the shard mapping — last, and only if the schema is actually gone.
    # The mapping is the only route to that schema, so clearing it after a failed
    # drop strands it on a shard nothing can resolve.
    if schema_dropped:
        try:
            clear_tenant_placement(tenant_id)
            logger.info("Successfully cleared shard mapping for tenant %s", tenant_id)
        except Exception as e:
            error_msg = (
                f"Failed to clear shard mapping for tenant {tenant_id}: {str(e)}"
            )
            logger.error(error_msg)
            rollback_errors.append(error_msg)
    else:
        logger.warning(
            "Keeping shard mapping for tenant %s: its schema was not dropped, and the "
            "mapping is what a retry needs to find it",
            tenant_id,
        )

    # Log summary of rollback operation
    if rollback_errors:
        logger.error("Tenant rollback completed with %s errors", len(rollback_errors))
    else:
        logger.info("Tenant rollback completed successfully for tenant %s", tenant_id)


def _build_model_configuration_upsert_requests(
    provider_name: str,
    recommendations: LLMRecommendations,
) -> list[ModelConfigurationUpsertRequest]:
    model_configurations = model_configurations_for_provider(
        provider_name, recommendations
    )
    return [
        ModelConfigurationUpsertRequest(
            name=model_configuration.name,
            is_visible=model_configuration.is_visible,
            max_input_tokens=model_configuration.max_input_tokens,
            supports_image_input=model_configuration.supports_image_input,
        )
        for model_configuration in model_configurations
    ]


def configure_default_api_keys(db_session: Session) -> None:
    """Configure default LLM providers using recommended-models.json for model selection."""
    # Load recommendations from JSON config
    recommendations = get_recommendations()

    has_set_default_provider = False

    def _upsert(request: LLMProviderUpsertRequest, default_model: str) -> None:
        nonlocal has_set_default_provider
        try:
            if request.name:
                existing = fetch_existing_llm_provider_by_name_and_type(
                    name=request.name,
                    provider_type=request.provider,
                    db_session=db_session,
                )
            else:
                existing = fetch_existing_llm_provider_by_type_nameless(
                    provider_type=request.provider, db_session=db_session
                )
            if existing:
                request.id = existing.id
            provider = upsert_llm_provider(request, db_session)
            if not has_set_default_provider:
                update_default_provider(provider.id, default_model, db_session)
                has_set_default_provider = True
        except Exception as e:
            logger.error("Failed to configure %s provider: %s", request.provider, e)

    # Configure OpenAI provider
    if OPENAI_DEFAULT_API_KEY and AUTO_PROVISION_DEFAULT_LLM_PROVIDERS:
        default_model = recommendations.get_default_model(OPENAI_PROVIDER_NAME)
        if default_model is None:
            logger.error(
                "No default model found for %s in recommendations", OPENAI_PROVIDER_NAME
            )
        default_model_name = default_model.name if default_model else "gpt-5.2"

        openai_provider = LLMProviderUpsertRequest(
            name="OpenAI",
            provider=OPENAI_PROVIDER_NAME,
            api_key=OPENAI_DEFAULT_API_KEY,
            model_configurations=_build_model_configuration_upsert_requests(
                OPENAI_PROVIDER_NAME, recommendations
            ),
            api_key_changed=True,
            is_auto_mode=True,
        )
        _upsert(openai_provider, default_model_name)

        # Create default image generation config using the OpenAI API key
        try:
            create_default_image_gen_config_from_api_key(
                db_session, OPENAI_DEFAULT_API_KEY
            )
        except Exception as e:
            logger.error("Failed to create default image gen config: %s", e)
    else:
        logger.info(
            "Skipping OpenAI default provider configuration "
            "(OPENAI_DEFAULT_API_KEY unset or AUTO_PROVISION_DEFAULT_LLM_PROVIDERS=false)"
        )

    # Configure Anthropic provider
    if ANTHROPIC_DEFAULT_API_KEY and AUTO_PROVISION_DEFAULT_LLM_PROVIDERS:
        default_model = recommendations.get_default_model(ANTHROPIC_PROVIDER_NAME)
        if default_model is None:
            logger.error(
                "No default model found for %s in recommendations",
                ANTHROPIC_PROVIDER_NAME,
            )
        default_model_name = (
            default_model.name if default_model else "claude-sonnet-4-5"
        )

        anthropic_provider = LLMProviderUpsertRequest(
            name="Anthropic",
            provider=ANTHROPIC_PROVIDER_NAME,
            api_key=ANTHROPIC_DEFAULT_API_KEY,
            model_configurations=_build_model_configuration_upsert_requests(
                ANTHROPIC_PROVIDER_NAME, recommendations
            ),
            api_key_changed=True,
            is_auto_mode=True,
        )
        _upsert(anthropic_provider, default_model_name)
    else:
        logger.info(
            "Skipping Anthropic default provider configuration "
            "(ANTHROPIC_DEFAULT_API_KEY unset or AUTO_PROVISION_DEFAULT_LLM_PROVIDERS=false)"
        )

    # Configure Vertex AI provider
    if VERTEXAI_DEFAULT_CREDENTIALS:
        default_model = recommendations.get_default_model(VERTEXAI_PROVIDER_NAME)
        if default_model is None:
            logger.error(
                "No default model found for %s in recommendations",
                VERTEXAI_PROVIDER_NAME,
            )
        default_model_name = default_model.name if default_model else "gemini-2.5-pro"

        # Vertex AI uses custom_config for credentials and location
        custom_config = {
            VERTEX_CREDENTIALS_FILE_KWARG: VERTEXAI_DEFAULT_CREDENTIALS,
            VERTEX_LOCATION_KWARG: VERTEXAI_DEFAULT_LOCATION,
        }

        vertexai_provider = LLMProviderUpsertRequest(
            name="Google Vertex AI",
            provider=VERTEXAI_PROVIDER_NAME,
            custom_config=custom_config,
            model_configurations=_build_model_configuration_upsert_requests(
                VERTEXAI_PROVIDER_NAME, recommendations
            ),
            api_key_changed=True,
            is_auto_mode=True,
        )
        _upsert(vertexai_provider, default_model_name)
    else:
        logger.info(
            "VERTEXAI_DEFAULT_CREDENTIALS not set, skipping Vertex AI provider configuration"
        )

    # Configure OpenRouter provider
    if OPENROUTER_DEFAULT_API_KEY and AUTO_PROVISION_DEFAULT_LLM_PROVIDERS:
        default_model = recommendations.get_default_model(OPENROUTER_PROVIDER_NAME)
        if default_model is None:
            logger.error(
                "No default model found for %s in recommendations",
                OPENROUTER_PROVIDER_NAME,
            )
        default_model_name = default_model.name if default_model else "z-ai/glm-4.7"

        # For OpenRouter, we use the visible models from recommendations as model_configurations
        # since OpenRouter models are dynamic (fetched from their API)
        visible_models = recommendations.get_visible_models(OPENROUTER_PROVIDER_NAME)
        model_configurations = [
            ModelConfigurationUpsertRequest(
                name=model.name,
                is_visible=True,
                max_input_tokens=None,
                display_name=model.display_name,
            )
            for model in visible_models
        ]

        openrouter_provider = LLMProviderUpsertRequest(
            name="OpenRouter",
            provider=OPENROUTER_PROVIDER_NAME,
            api_key=OPENROUTER_DEFAULT_API_KEY,
            model_configurations=model_configurations,
            api_key_changed=True,
            is_auto_mode=True,
        )
        _upsert(openrouter_provider, default_model_name)
    else:
        logger.info(
            "Skipping OpenRouter default provider configuration "
            "(OPENROUTER_DEFAULT_API_KEY unset or AUTO_PROVISION_DEFAULT_LLM_PROVIDERS=false)"
        )

    # Configure Cohere embedding provider
    if COHERE_DEFAULT_API_KEY:
        cloud_embedding_provider = CloudEmbeddingProviderCreationRequest(
            provider_type=EmbeddingProvider.COHERE,
            api_key=COHERE_DEFAULT_API_KEY,
        )

        try:
            logger.info("Attempting to upsert Cohere cloud embedding provider")
            upsert_cloud_embedding_provider(db_session, cloud_embedding_provider)
            logger.info("Successfully upserted Cohere cloud embedding provider")

            logger.info("Updating search settings with Cohere embedding model details")
            query = (
                select(SearchSettings)
                .where(SearchSettings.status == IndexModelStatus.FUTURE)
                .order_by(SearchSettings.id.desc())
            )
            result = db_session.execute(query)
            current_search_settings = result.scalars().first()

            if current_search_settings:
                current_search_settings.model_name = (
                    "embed-english-v3.0"  # Cohere's latest model as of now
                )
                current_search_settings.model_dim = (
                    1024  # Cohere's embed-english-v3.0 dimension
                )
                current_search_settings.provider_type = EmbeddingProvider.COHERE
                current_search_settings.index_name = (
                    "danswer_chunk_cohere_embed_english_v3_0"
                )
                current_search_settings.query_prefix = ""
                current_search_settings.passage_prefix = ""
                db_session.commit()
            else:
                raise RuntimeError(
                    "No search settings specified, DB is not in a valid state"
                )
            logger.info("Fetching updated search settings to verify changes")
            updated_query = (
                select(SearchSettings)
                .where(SearchSettings.status == IndexModelStatus.PRESENT)
                .order_by(SearchSettings.id.desc())
            )
            updated_result = db_session.execute(updated_query)
            updated_result.scalars().first()

        except Exception:
            logger.exception("Failed to configure Cohere embedding provider")
    else:
        logger.info(
            "COHERE_DEFAULT_API_KEY not set, skipping Cohere embedding provider configuration"
        )


async def submit_to_hubspot(
    email: str, referral_source: str | None, request: Request
) -> None:
    if not HUBSPOT_TRACKING_URL:
        logger.info("HUBSPOT_TRACKING_URL not set, skipping HubSpot submission")
        return

    # HubSpot tracking cookie
    hubspot_cookie = request.cookies.get("hubspotutk")

    # IP address
    ip_address = request.client.host if request.client else None

    data = {
        "fields": [
            {"name": "email", "value": email},
            {"name": "referral_source", "value": referral_source or ""},
        ],
        "context": {
            "hutk": hubspot_cookie,
            "ipAddress": ip_address,
            "pageUri": str(request.url),
            "pageName": "User Registration",
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(HUBSPOT_TRACKING_URL, json=data)

    if response.status_code != 200:
        logger.error("Failed to submit to HubSpot: %s", response.text)


async def delete_user_from_control_plane(tenant_id: str, email: str) -> None:
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = TenantDeletionPayload(tenant_id=tenant_id, email=email)

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{CONTROL_PLANE_API_BASE_URL}/tenants/delete",
            headers=headers,
            json=payload.model_dump(),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error("Control plane tenant creation failed: %s", error_text)
                raise Exception(
                    f"Failed to delete tenant on control plane: {error_text}"
                )


def get_tenant_by_domain_from_control_plane(
    domain: str,
    tenant_id: str,
) -> TenantByDomainResponse | None:
    """
    Fetches tenant information from the control plane based on the email domain.

    Args:
        domain: The email domain to search for (e.g., "example.com")

    Returns:
        A dictionary containing tenant information if found, None otherwise
    """
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{CONTROL_PLANE_API_BASE_URL}/tenant-by-domain",
            headers=headers,
            json={"domain": domain, "tenant_id": tenant_id},
            timeout=_CONTROL_PLANE_TIMEOUT_S,
        )

        if response.status_code != 200:
            logger.error("Control plane tenant lookup failed: %s", response.text)
            return None

        response_data = response.json()
        if not response_data:
            return None

        return TenantByDomainResponse(
            tenant_id=response_data.get("tenant_id"),
            number_of_users=response_data.get("number_of_users"),
            creator_email=response_data.get("creator_email"),
        )
    except Exception as e:
        logger.error("Error fetching tenant by domain: %s", str(e))
        return None


async def get_available_tenant(allow_stale: bool = False) -> PoolTenant | None:
    """
    Take the oldest pre-provisioned tenant out of the pool, or None if the pool
    is empty. Uses row-level locking to prevent race conditions when multiple
    processes try to get an available tenant simultaneously.

    A tenant behind the code's head revision stays in the pool unless
    ``allow_stale`` is set, since only a worker may migrate it. The refill task
    migrates pool tenants on every run, so a stale head is short-lived.
    """
    if not MULTI_TENANT:
        return None

    at_revision = None if allow_stale else get_alembic_head_revision()
    with get_session_with_shared_schema() as db_session:
        try:
            db_session.begin()
            taken = take_available_tenant(db_session, at_revision)
        except Exception:
            logger.exception("Error getting available tenant")
            db_session.rollback()
            return None

    if taken is None:
        return None
    tenant_id, alembic_version = taken
    logger.info("Using pre-provisioned tenant %s", tenant_id)
    return PoolTenant(tenant_id=tenant_id, alembic_version=alembic_version)


async def setup_tenant(tenant_id: str) -> None:
    """
    Set up a tenant with all necessary configurations.
    This is a centralized function that handles all tenant setup logic.
    """
    token = None
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

        # Run Alembic migrations in a way that isolates it from the current event loop
        # Create a new event loop for this synchronous operation
        loop = asyncio.get_event_loop()
        # Use run_in_executor which properly isolates the thread execution
        await loop.run_in_executor(None, lambda: run_alembic_migrations(tenant_id))

        # Configure the tenant with default settings
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Configure default API keys
            configure_default_api_keys(db_session)

            # Set up Onyx with appropriate settings
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

    except Exception as e:
        logger.exception("Failed to set up tenant %s", tenant_id)
        raise e
    finally:
        if token is not None:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


async def assign_tenant_to_user(
    tenant_id: str,
    email: str,
    referral_source: str | None = None,  # noqa: ARG001
) -> None:
    """
    Assign a tenant to a user and perform necessary operations.
    Uses transaction handling to ensure atomicity and includes retry logic
    for control plane notifications.
    """
    # First, add the user to the tenant in a transaction

    try:
        add_users_to_tenant([email], tenant_id)
    except Exception:
        logger.exception("Failed to assign tenant %s to user %s", tenant_id, email)
        raise Exception("Failed to assign tenant to user")
