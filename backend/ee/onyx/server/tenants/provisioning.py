import asyncio
import logging
import uuid

import aiohttp  # Async HTTP client
import httpx
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import HUBSPOT_TRACKING_URL
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.server.tenants.async_setup import complete_tenant_setup
from ee.onyx.server.tenants.models import TenantCreationPayload
from ee.onyx.server.tenants.models import TenantDeletionPayload
from ee.onyx.server.tenants.schema_management import create_schema_if_not_exists
from ee.onyx.server.tenants.schema_management import drop_schema
from ee.onyx.server.tenants.schema_management import run_essential_alembic_migrations
from ee.onyx.server.tenants.user_mapping import add_users_to_tenant
from ee.onyx.server.tenants.user_mapping import get_tenant_id_for_email
from ee.onyx.server.tenants.user_mapping import user_owns_a_tenant
from onyx.auth.users import exceptions
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.app_configs import DEV_MODE
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.models import UserTenantMapping
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


logger = logging.getLogger(__name__)


async def get_or_provision_tenant(
    email: str, referral_source: str | None = None, request: Request | None = None
) -> str:
    """Get existing tenant ID for an email or create a new tenant if none exists."""
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    if referral_source and request:
        await submit_to_hubspot(email, referral_source, request)

    try:
        tenant_id = get_tenant_id_for_email(email)
    except exceptions.UserNotExists:
        # If tenant does not exist and in Multi tenant mode, provision a new tenant
        try:
            tenant_id = await create_tenant(email, referral_source)
        except Exception as e:
            logger.error(f"Tenant provisioning failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to provision tenant.")

    if not tenant_id:
        raise HTTPException(
            status_code=401, detail="User does not belong to an organization"
        )

    return tenant_id


async def create_tenant(email: str, referral_source: str | None = None) -> str:
    tenant_id = TENANT_ID_PREFIX + str(uuid.uuid4())
    try:
        # Provision tenant on data plane
        await provision_tenant(tenant_id, email)
        # Notify control plane
        if not DEV_MODE:
            await notify_control_plane(tenant_id, email, referral_source)
    except Exception as e:
        logger.error(f"Tenant provisioning failed: {e}")
        await rollback_tenant_provisioning(tenant_id)
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
    token = None

    try:
        if not create_schema_if_not_exists(tenant_id):
            logger.debug(f"Created schema for tenant {tenant_id}")
        else:
            logger.debug(f"Schema already exists for tenant {tenant_id}")

        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

        # Run only the essential Alembic migrations needed for auth
        await asyncio.to_thread(run_essential_alembic_migrations, tenant_id)

        # Add user to tenant immediately so they can log in
        add_users_to_tenant([email], tenant_id)

        # Start the rest of the setup process asynchronously
        asyncio.create_task(complete_tenant_setup(tenant_id, email))

        logger.info(f"Essential tenant provisioning completed for tenant {tenant_id}")
        logger.info(
            f"Remaining setup will continue asynchronously for tenant {tenant_id}"
        )

    except Exception as e:
        logger.exception(f"Failed to create tenant {tenant_id}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create tenant: {str(e)}"
        )
    finally:
        if token is not None:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


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
    # Logic to rollback tenant provisioning on data plane
    logger.info(f"Rolling back tenant provisioning for tenant_id: {tenant_id}")
    try:
        # Drop the tenant's schema to rollback provisioning
        drop_schema(tenant_id)

        # Remove tenant mapping
        with Session(get_sqlalchemy_engine()) as db_session:
            db_session.query(UserTenantMapping).filter(
                UserTenantMapping.tenant_id == tenant_id
            ).delete()
            db_session.commit()
    except Exception as e:
        logger.error(f"Failed to rollback tenant provisioning: {e}")


async def submit_to_hubspot(
    email: str, referral_source: str | None, request: Request
) -> None:
    if not HUBSPOT_TRACKING_URL:
        return

    try:
        user_agent = request.headers.get("user-agent", "")
        referer = request.headers.get("referer", "")
        ip_address = request.client.host if request.client else ""

        payload = {
            "email": email,
            "referral_source": referral_source or "",
            "user_agent": user_agent,
            "referer": referer,
            "ip_address": ip_address,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                HUBSPOT_TRACKING_URL,
                json=payload,
                timeout=5.0,
            )
            if response.status_code != 200:
                logger.error(
                    f"Failed to submit to HubSpot: {response.status_code} {response.text}"
                )
    except Exception as e:
        logger.error(f"Error submitting to HubSpot: {e}")


async def delete_user_from_control_plane(tenant_id: str, email: str) -> None:
    if DEV_MODE:
        return

    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = TenantDeletionPayload(tenant_id=tenant_id, email=email)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CONTROL_PLANE_API_BASE_URL}/tenants/delete",
            headers=headers,
            json=payload.model_dump(),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Control plane tenant deletion failed: {error_text}")
                raise Exception(
                    f"Failed to delete tenant on control plane: {error_text}"
                )
