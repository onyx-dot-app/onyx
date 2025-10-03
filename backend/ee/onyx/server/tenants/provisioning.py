import asyncio
import logging
import uuid

import aiohttp  # Async HTTP client
import httpx
import requests
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import ANTHROPIC_DEFAULT_API_KEY
from ee.onyx.configs.app_configs import COHERE_DEFAULT_API_KEY
from ee.onyx.configs.app_configs import HUBSPOT_TRACKING_URL
from ee.onyx.configs.app_configs import OPENAI_DEFAULT_API_KEY
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.models import TenantByDomainResponse
from ee.onyx.server.tenants.models import TenantCreationPayload
from ee.onyx.server.tenants.models import TenantDeletionPayload
from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists
from ee.onyx.server.tenants.schema_management import drop_schema
from ee.onyx.server.tenants.schema_management import run_alembic_migrations
from ee.onyx.server.tenants.user_mapping import add_users_to_tenant
from ee.onyx.server.tenants.user_mapping import get_tenant_id_for_email
from ee.onyx.server.tenants.user_mapping import user_owns_a_tenant
from onyx.auth.users import exceptions
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.constants import MilestoneRecordType
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_cloud_embedding_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import AvailableTenant
from onyx.db.models import IndexModelStatus
from onyx.db.models import SearchSettings
from onyx.db.models import UserTenantMapping
from onyx.llm.llm_provider_options import ANTHROPIC_PROVIDER_NAME
from onyx.llm.llm_provider_options import ANTHROPIC_VISIBLE_MODEL_NAMES
from onyx.llm.llm_provider_options import get_anthropic_model_names
from onyx.llm.llm_provider_options import OPEN_AI_MODEL_NAMES
from onyx.llm.llm_provider_options import OPEN_AI_VISIBLE_MODEL_NAMES
from onyx.llm.llm_provider_options import OPENAI_PROVIDER_NAME
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.setup import setup_onyx
from onyx.utils.telemetry import create_milestone_and_report
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.enums import EmbeddingProvider


logger = logging.getLogger(__name__)


async def get_or_provision_tenant(
    email: str, referral_source: str | None = None, request: Request | None = None
) -> str:
    """
    Get existing tenant ID for an email or create a new tenant if none exists.
    This function should only be called after we have verified we want this user's tenant to exist.
    It returns the tenant ID associated with the email, creating a new tenant if necessary.
    """
    # Early return for non-multi-tenant mode
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    if referral_source and request:
        await submit_to_hubspot(email, referral_source, request)

    # First, check if the user already has a tenant
    tenant_id: str | None = None
    try:
        tenant_id = get_tenant_id_for_email(email)
        return tenant_id
    except exceptions.UserNotExists:
        # User doesn't exist, so we need to create a new tenant or assign an existing one
        pass

    try:
        # Try to get a pre-provisioned tenant
        tenant_id = await get_available_tenant()

        if tenant_id:
            # If we have a pre-provisioned tenant, assign it to the user
            await assign_tenant_to_user(tenant_id, email, referral_source)
            logger.info(f"Assigned pre-provisioned tenant {tenant_id} to user {email}")
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
        raise HTTPException(
            status_code=500,
            detail="Failed to provision tenant. Please try again later.",
        )


async def create_tenant(email: str, referral_source: str | None = None) -> str:
    """
    Create a new tenant on-demand when no pre-provisioned tenants are available.
    This is the fallback method when we can't use a pre-provisioned tenant.

    """
    tenant_id = TENANT_ID_PREFIX + str(uuid.uuid4())
    logger.info(f"Creating new tenant {tenant_id} for user {email}")

    try:
        # Provision tenant on data plane
        await provision_tenant(tenant_id, email)

    except Exception as e:
        logger.exception(f"Tenant provisioning failed: {str(e)}")
        # Attempt to rollback the tenant provisioning
        try:
            await rollback_tenant_provisioning(tenant_id)
        except Exception:
            logger.exception(f"Failed to rollback tenant provisioning for {tenant_id}")
        raise HTTPException(status_code=500, detail="Failed to provision tenant.")

    return tenant_id


async def provision_tenant(tenant_id: str, email: str) -> None:
    if not MULTI_TENANT:
        raise HTTPException(status_code=403, detail="Multi-tenancy is not enabled")

    if user_owns_a_tenant(email):
        raise HTTPException(
            status_code=409, detail="User already belongs to an organization"
        )

    logger.debug(f"Provisioning tenant {tenant_id} for user {email}")

    try:
        # Create the schema for the tenant
        if not create_schema_if_not_exists(tenant_id):
            logger.debug(f"Created schema for tenant {tenant_id}")
        else:
            logger.debug(f"Schema already exists for tenant {tenant_id}")

        # Set up the tenant with all necessary configurations
        await setup_tenant(tenant_id)

        # Assign the tenant to the user
        await assign_tenant_to_user(tenant_id, email)

    except Exception as e:
        logger.exception(f"Failed to create tenant {tenant_id}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create tenant: {str(e)}"
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
                logger.error(f"Control plane tenant creation failed: {error_text}")
                raise Exception(
                    f"Failed to create tenant on control plane: {error_text}"
                )


async def rollback_tenant_provisioning(tenant_id: str) -> None:
    """
    Logic to rollback tenant provisioning on data plane.
    Handles each step independently to ensure maximum cleanup even if some steps fail.
    """
    logger.info(f"Rolling back tenant provisioning for tenant_id: {tenant_id}")

    # Track if any part of the rollback fails
    rollback_errors = []

    # 1. Try to drop the tenant's schema
    try:
        drop_schema(tenant_id)
        logger.info(f"Successfully dropped schema for tenant {tenant_id}")
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
                    f"Successfully removed user mappings for tenant {tenant_id}"
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
                        f"Removed tenant {tenant_id} from available tenants table"
                    )
            except Exception as e:
                db_session.rollback()
                raise e
    except Exception as e:
        error_msg = f"Failed to remove tenant {tenant_id} from available tenants table: {str(e)}"
        logger.error(error_msg)
        rollback_errors.append(error_msg)

    # Log summary of rollback operation
    if rollback_errors:
        logger.error(f"Tenant rollback completed with {len(rollback_errors)} errors")
    else:
        logger.info(f"Tenant rollback completed successfully for tenant {tenant_id}")


def configure_default_api_keys(db_session: Session) -> None:
    if ANTHROPIC_DEFAULT_API_KEY:
        anthropic_provider = LLMProviderUpsertRequest(
            name="Anthropic",
            provider=ANTHROPIC_PROVIDER_NAME,
            api_key=ANTHROPIC_DEFAULT_API_KEY,
            default_model_name="claude-3-7-sonnet-20250219",
            fast_default_model_name="claude-3-5-sonnet-20241022",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=name,
                    is_visible=name in ANTHROPIC_VISIBLE_MODEL_NAMES,
                    max_input_tokens=None,
                )
                for name in get_anthropic_model_names()
            ],
            api_key_changed=True,
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
        openai_provider = LLMProviderUpsertRequest(
            name="OpenAI",
            provider=OPENAI_PROVIDER_NAME,
            api_key=OPENAI_DEFAULT_API_KEY,
            default_model_name="gpt-4o",
            fast_default_model_name="gpt-4o-mini",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=model_name in OPEN_AI_VISIBLE_MODEL_NAMES,
                    max_input_tokens=None,
                )
                for model_name in OPEN_AI_MODEL_NAMES
            ],
            api_key_changed=True,
        )
        try:
            full_provider = upsert_llm_provider(openai_provider, db_session)
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
        logger.error(f"Failed to submit to HubSpot: {response.text}")


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
                logger.error(f"Control plane tenant creation failed: {error_text}")
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
        )

        if response.status_code != 200:
            logger.error(f"Control plane tenant lookup failed: {response.text}")
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
        logger.error(f"Error fetching tenant by domain: {str(e)}")
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
            available_tenant = (
                db_session.query(AvailableTenant)
                .order_by(AvailableTenant.date_created)
                .with_for_update(skip_locked=True)  # Skip locked rows to avoid blocking
                .first()
            )

            if available_tenant:
                tenant_id = available_tenant.tenant_id
                # Remove the tenant from the available tenants table
                db_session.delete(available_tenant)
                db_session.commit()
                logger.info(f"Using pre-provisioned tenant {tenant_id}")
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
        logger.exception(f"Failed to set up tenant {tenant_id}")
        raise e
    finally:
        if token is not None:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


async def assign_tenant_to_user(
    tenant_id: str, email: str, referral_source: str | None = None
) -> None:
    """
    Assign a tenant to a user and perform necessary operations.
    Uses transaction handling to ensure atomicity and includes retry logic
    for control plane notifications.
    """
    # First, add the user to the tenant in a transaction

    try:
        add_users_to_tenant([email], tenant_id)

        # Create milestone record in the same transaction context as the tenant assignment
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
    except Exception:
        logger.exception(f"Failed to assign tenant {tenant_id} to user {email}")
        raise Exception("Failed to assign tenant to user")
