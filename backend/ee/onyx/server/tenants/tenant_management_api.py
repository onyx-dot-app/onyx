from fastapi import APIRouter
from fastapi import Depends

from ee.onyx.server.tenants.models import TenantByDomainResponse
from ee.onyx.server.tenants.provisioning import get_tenant_by_domain_from_control_plane
from onyx.auth.users import current_user
from onyx.auth.users import User
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")

FORBIDDEN_COMMON_EMAIL_DOMAINS = [
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "msn.com",
    "live.com",
    "msn.com",
    "hotmail.com",
    "hotmail.co.uk",
    "hotmail.fr",
    "hotmail.de",
    "hotmail.it",
    "hotmail.es",
    "hotmail.nl",
    "hotmail.pl",
    "hotmail.pt",
    "hotmail.ro",
    "hotmail.ru",
    "hotmail.sa",
    "hotmail.se",
    "hotmail.tr",
    "hotmail.tw",
    "hotmail.ua",
    "hotmail.us",
    "hotmail.vn",
    "hotmail.za",
    "hotmail.zw",
]


@router.get("/existing-team-by-domain")
def get_existing_tenant_by_domain(
    user: User | None = Depends(current_user),
) -> TenantByDomainResponse | None:
    if not user:
        return None
    domain = user.email.split("@")[1]
    if domain in FORBIDDEN_COMMON_EMAIL_DOMAINS:
        return None
    tenant_id = get_current_tenant_id()

    return get_tenant_by_domain_from_control_plane(domain, tenant_id)
