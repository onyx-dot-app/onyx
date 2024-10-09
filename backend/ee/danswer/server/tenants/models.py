from pydantic import BaseModel


class CreateTenantRequest(BaseModel):
    tenant_id: str
    initial_admin_email: str
