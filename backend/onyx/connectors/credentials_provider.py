import uuid
from types import TracebackType
from typing import Any

from redis.lock import Lock as RedisLock
from sqlalchemy import select

from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import Credential
from onyx.redis.redis_pool import get_redis_client


class OnyxDBCredentialsProvider(
    CredentialsProviderInterface["OnyxDBCredentialsProvider"]
):
    """Implementation to allow the connector to callback and update credentials in the db.
    Required in cases where credentials can rotate while the connector is running.
    """

    LOCK_TTL = 900  # TTL of the lock

    def __init__(self, tenant_id: str, connector_name: str, credential_id: int):
        self._tenant_id = tenant_id
        self._connector_name = connector_name
        self._credential_id = credential_id

        self.redis_client = get_redis_client(tenant_id=tenant_id)

        # lock used to prevent overlapping renewal of credentials
        self.lock_key = f"da_lock:connector:{connector_name}:credential_{credential_id}"
        self._lock: RedisLock = self.redis_client.lock(self.lock_key, self.LOCK_TTL)

    def __enter__(self) -> "OnyxDBCredentialsProvider":
        acquired = self._lock.acquire(blocking_timeout=self.LOCK_TTL)
        if not acquired:
            raise RuntimeError(f"Could not acquire lock for key: {self.lock_key}")

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the lock when exiting the context."""
        if self._lock and self._lock.owned():
            self._lock.release()

    def get_tenant_id(self) -> str | None:
        return self._tenant_id

    def get_provider_key(self) -> str:
        return str(self._credential_id)

    def get_credentials(self) -> dict[str, Any]:
        with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
            credential = db_session.execute(
                select(Credential).where(Credential.id == self._credential_id)
            ).scalar_one()

            if credential is None:
                raise ValueError(
                    f"No credential found: credential={self._credential_id}"
                )

            return credential.credential_json

    def set_credentials(self, credential_json: dict[str, Any]) -> None:
        with get_session_with_tenant(tenant_id=self._tenant_id) as db_session:
            try:
                credential = db_session.execute(
                    select(Credential)
                    .where(Credential.id == self._credential_id)
                    .with_for_update()
                ).scalar_one()

                if credential is None:
                    raise ValueError(
                        f"No credential found: credential={self._credential_id}"
                    )

                credential.credential_json = credential_json
                db_session.commit()
            except Exception:
                db_session.rollback()
                raise

    def is_dynamic(self) -> bool:
        return True


class OnyxStaticCredentialsProvider(
    CredentialsProviderInterface["OnyxStaticCredentialsProvider"]
):
    """Implementation (a very simple one!) to handle static credentials."""

    def __init__(
        self,
        tenant_id: str | None,
        connector_name: str,
        credential_json: dict[str, Any],
    ):
        self._tenant_id = tenant_id
        self._connector_name = connector_name
        self._credential_json = credential_json

        self._provider_key = str(uuid.uuid4())

    def __enter__(self) -> "OnyxStaticCredentialsProvider":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    def get_tenant_id(self) -> str | None:
        return self._tenant_id

    def get_provider_key(self) -> str:
        return self._provider_key

    def get_credentials(self) -> dict[str, Any]:
        return self._credential_json

    def set_credentials(self, credential_json: dict[str, Any]) -> None:
        self._credential_json = credential_json

    def is_dynamic(self) -> bool:
        return False
