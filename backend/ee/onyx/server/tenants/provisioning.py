import asyncio
import uuid

import aiohttp  # Async HTTP client
import httpx
import requests
from fastapi import Request
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import HUBSPOT_TRACKING_URL
from ee.onyx.db.tenant_provisioning import (
    delete_available_tenant__no_commit,
    get_available_tenant_by_id,
    get_first_search_settings_by_status,
    get_latest_search_settings_by_status,
    lock_oldest_available_tenant,
)
from ee.onyx.db.user_tenant_mapping import (
    add_users_to_tenant,
    delete_user_tenant_mappings__no_commit,
    resolve_tenant_id,
    user_owns_a_tenant,
)
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.models import (
    SignUpDomainState,
    TenantByDomainResponse,
    TenantCreationPayload,
    TenantDeletionPayload,
)
from ee.onyx.server.tenants.schema_management import (
    build_tenant_schema,
    create_schema_if_not_exists,
    drop_schema,
    run_alembic_migrations,
)
from onyx.auth.free_mail_email_validator import is_free_mail_email
from onyx.configs.app_configs import (
    ANTHROPIC_DEFAULT_API_KEY,
    AUTO_PROVISION_DEFAULT_LLM_PROVIDERS,
    COHERE_DEFAULT_API_KEY,
    CONTROL_PLANE_API_BASE_URL,
    DEV_MODE,
    OPENAI_DEFAULT_API_KEY,
    OPENROUTER_DEFAULT_API_KEY,
    VERTEXAI_DEFAULT_CREDENTIALS,
    VERTEXAI_DEFAULT_LOCATION,
)
from onyx.configs.model_configs import DEFAULT_OPENAI_MODEL
from onyx.db.engine.shard_routing import get_shard_for_new_tenant
from onyx.db.engine.sql_engine import (
    get_session_with_shared_schema,
    get_session_with_tenant,
)
from onyx.db.enums import LLMModelFlowType
from onyx.db.image_generation import create_default_image_gen_config_from_api_key
from onyx.db.llm import (
    fetch_existing_llm_provider_by_name_and_type,
    fetch_existing_llm_provider_by_type_nameless,
    update_default_model,
    upsert_cloud_embedding_provider,
    upsert_llm_provider,
)
from onyx.db.models import IndexModelStatus
from onyx.db.search_settings import get_secondary_search_settings
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
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.setup import setup_onyx
from onyx.utils.logger import setup_logger
from shared_configs.configs import (
    IS_PLAYGROUND,
    MULTI_TENANT,
    POSTGRES_DEFAULT_SCHEMA,
    TENANT_ID_PREFIX,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.enums import EmbeddingProvider

logger = setup_logger()

# Matches billing.py. Without it a hung control plane pins the caller forever.
_CONTROL_PLANE_TIMEOUT_S = 30


async def get_or_provision_tenant(
    email: str,
    referral_source: str | None = None,
    request: Request | None = None,
    oauth_name: str | None = None,
    account_id: str | None = None,
    start_new_team: bool = False,
) -> str:
    """
    Get existing tenant ID for an email or create a new tenant if none exists.
    This function should only be called after we have verified we want this user's tenant to exist.
    It returns the tenant ID associated with the email, creating a new tenant if necessary.

    When the caller knows the IdP subject it is tried before the email, which is
    what stops a renamed user being treated as a brand new signup.

    On the playground `start_new_team` says the person chose to start a new team
    although a team from their domain has a running trial.
    """
    # Early return for non-multi-tenant mode
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    if referral_source and request:
        await submit_to_hubspot(email, referral_source, request)

    tenant_id = resolve_tenant_id(email, oauth_name, account_id)
    if tenant_id:
        return tenant_id

    # Before the try below: a refusal must reach the person, not become a 500.
    if IS_PLAYGROUND:
        await check_playground_sign_up(email, start_new_team)

    try:
        # Try to get a pre-provisioned tenant
        tenant_id = await get_available_tenant()

        if tenant_id:
            # Run migrations to ensure the pre-provisioned tenant schema is current.
            # Pool tenants may have been created before a new migration was deployed.
            # Capture as a non-optional local so type-checking can type the lambda correctly.
            _tenant_id: str = tenant_id
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None, lambda: run_alembic_migrations(_tenant_id)
                )
            except Exception:
                # The tenant was already dequeued from the pool — roll it back so
                # it doesn't end up orphaned (schema exists, but not assigned to anyone).
                logger.exception(
                    "Migration failed for pre-provisioned tenant %s; rolling back",
                    _tenant_id,
                )
                try:
                    await rollback_tenant_provisioning(_tenant_id)
                except Exception:
                    logger.exception(
                        "Failed to rollback orphaned tenant %s", _tenant_id
                    )
                raise
            # If we have a pre-provisioned tenant, assign it to the user
            await assign_tenant_to_user(tenant_id, email, referral_source)
            logger.info(
                "Assigned pre-provisioned tenant %s to user %s", tenant_id, email
            )
        else:
            # If no pre-provisioned tenant is available, create a new one on-demand
            tenant_id = await create_tenant(email, referral_source)

        # Notify control plane if we have created / assigned a new tenant
        if not DEV_MODE:
            await notify_control_plane(tenant_id, email, referral_source)

        return tenant_id

    except Exception as e:
        # If we've encountered an error, log and raise an exception
        error_msg = "Failed to provision tenant"
        logger.error(error_msg, exc_info=e)
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Failed to provision tenant. Please try again later.",
        )


# The web shows a page for each code: contact sales, or join-or-new.
PLAYGROUND_REFUSAL_CODES = {
    SignUpDomainState.EMAIL_USED: "PLAYGROUND_EMAIL_USED",
    SignUpDomainState.LIMIT_REACHED: "PLAYGROUND_LIMIT_REACHED",
    SignUpDomainState.ACTIVE_TENANT: "PLAYGROUND_ACTIVE_TENANT",
}
# The control plane did not answer, so the rules could not run.
PLAYGROUND_CHECK_FAILED_CODE = "PLAYGROUND_CHECK_FAILED"
# Not a work address: the web asks for one. Decided here, without the
# control plane, since it depends on the address alone.
PLAYGROUND_FREE_MAIL_CODE = "PLAYGROUND_FREE_MAIL"


async def fetch_sign_up_domain_state(email: str) -> SignUpDomainState:
    """What the control plane says a playground sign-up from this address
    runs into. Raises when the control plane is down or answers badly.
    """
    headers = {
        "Authorization": f"Bearer {generate_data_plane_token()}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_CONTROL_PLANE_TIMEOUT_S) as client:
        response = await client.post(
            f"{CONTROL_PLANE_API_BASE_URL}/sign-up-domain",
            headers=headers,
            json={"email": email},
        )
    response.raise_for_status()
    return SignUpDomainState(response.json()["state"])


async def check_playground_sign_up(email: str, start_new_team: bool) -> None:
    """Refuses a playground sign-up that is not from a work address, or that
    the control plane rules out.

    A free-mail address is refused first: it is not one company, so the
    domain rules do not apply and the control plane is not asked.
    `active_tenant` passes when the person chose to start a new team. A
    control plane that cannot answer refuses too: no tenant without the rules.
    """
    if is_free_mail_email(email):
        logger.info(
            "Playground sign-up refused: free-mail domain %s",
            email.rsplit("@", 1)[-1].lower(),
        )
        raise OnyxError(OnyxErrorCode.REGISTRATION_DISABLED, PLAYGROUND_FREE_MAIL_CODE)
    try:
        state = await fetch_sign_up_domain_state(email)
    except Exception:
        logger.exception("Control plane sign-up check failed")
        raise OnyxError(
            OnyxErrorCode.REGISTRATION_DISABLED, PLAYGROUND_CHECK_FAILED_CODE
        )
    if state is SignUpDomainState.NEW:
        return
    if state is SignUpDomainState.ACTIVE_TENANT and start_new_team:
        return
    raise OnyxError(
        OnyxErrorCode.REGISTRATION_DISABLED, PLAYGROUND_REFUSAL_CODES[state]
    )


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
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Multi-tenancy is not enabled")

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

        # Set up the tenant with all necessary configurations
        await setup_tenant(tenant_id)

        # Assign the tenant to the user
        await assign_tenant_to_user(tenant_id, email)

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
                delete_user_tenant_mappings__no_commit(db_session, tenant_id)
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
                available_tenant = get_available_tenant_by_id(db_session, tenant_id)

                if available_tenant:
                    delete_available_tenant__no_commit(db_session, available_tenant)
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
                update_default_model(
                    provider_id=provider.id,
                    model=default_model,
                    db_session=db_session,
                    flow_type=LLMModelFlowType.CHAT,
                )
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
        default_model_name = (
            default_model.name if default_model else DEFAULT_OPENAI_MODEL
        )

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
        default_model_name = default_model.name if default_model else "claude-sonnet-5"

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
            current_search_settings = get_secondary_search_settings(db_session)

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
            get_latest_search_settings_by_status(db_session, IndexModelStatus.PRESENT)

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


async def get_available_tenant() -> str | None:
    """
    Get an available pre-provisioned tenant from the NewAvailableTenant table.
    Returns the tenant_id if one is available, None otherwise.
    Uses row-level locking to prevent race conditions when multiple processes
    try to get an available tenant simultaneously.
    """
    if not MULTI_TENANT:
        return None

    with get_session_with_shared_schema() as db_session:
        try:
            db_session.begin()

            # Get the oldest available tenant with FOR UPDATE lock to prevent race conditions
            available_tenant = lock_oldest_available_tenant(db_session)

            if available_tenant:
                tenant_id = available_tenant.tenant_id
                # Remove the tenant from the available tenants table
                delete_available_tenant__no_commit(db_session, available_tenant)
                db_session.commit()
                logger.info("Using pre-provisioned tenant %s", tenant_id)
                return tenant_id
            else:
                db_session.rollback()
                return None
        except Exception:
            logger.exception("Error getting available tenant")
            db_session.rollback()
            return None


async def setup_tenant(tenant_id: str) -> None:
    """
    Set up a tenant with all necessary configurations.
    This is a centralized function that handles all tenant setup logic.
    """
    token = None
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

        # Both paths block on Postgres, so they run off the event loop.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: build_tenant_schema(tenant_id))

        # Configure the tenant with default settings
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Configure default API keys
            configure_default_api_keys(db_session)

            # Set up Onyx with appropriate settings
            current_search_settings = get_first_search_settings_by_status(
                db_session, IndexModelStatus.FUTURE
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
