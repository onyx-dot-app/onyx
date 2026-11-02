"""Sandbox identity and verified session models."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SandboxIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str


class ResolvedSandbox(BaseModel):
    """Sandbox identity + owning user. Authorizes egress."""

    model_config = ConfigDict(frozen=True)

    sandbox_id: UUID
    user_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str

    def with_session(self, session_id: UUID) -> "SessionContext":
        return SessionContext(
            session_id=session_id,
            user_id=self.user_id,
            sandbox_id=self.sandbox_id,
            tenant_id=self.tenant_id,
            sandbox_name=self.sandbox_name,
            sandbox_ip=self.sandbox_ip,
        )


class SessionContext(BaseModel):
    """Sandbox identity + the verified session to route the card to."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    user_id: UUID
    sandbox_id: UUID
    tenant_id: str
    sandbox_name: str
    sandbox_ip: str

    def without_session(self) -> ResolvedSandbox:
        """
        Inverse of `ResolvedSandbox.with_session(...)` — drops the session id.
        """
        return ResolvedSandbox(
            sandbox_id=self.sandbox_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            sandbox_name=self.sandbox_name,
            sandbox_ip=self.sandbox_ip,
        )
