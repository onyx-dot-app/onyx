import json
from typing import Any

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_BOX_JWT_CONFIG
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Key for Box JWT config in credentials dict
DB_CREDENTIALS_DICT_BOX_JWT_CONFIG = "box_jwt_config"
# Key for primary admin user ID in credentials dict
DB_CREDENTIALS_PRIMARY_ADMIN_USER_ID = "box_primary_admin_user_id"
# Authentication method indicator
DB_CREDENTIALS_AUTHENTICATION_METHOD = "authentication_method"
BOX_AUTHENTICATION_METHOD_UPLOADED = "uploaded"


class BoxJWTConfig(BaseModel):
    """Box JWT configuration from JSON file."""

    boxAppSettings: dict[str, Any]
    enterpriseID: str | None = None

    def model_post_init(self, __context: Any) -> None:
        """Validate required nested keys after model initialization."""
        # Validate boxAppSettings structure
        if not isinstance(self.boxAppSettings, dict):
            raise ValueError(
                f"boxAppSettings must be a dict, got {type(self.boxAppSettings).__name__}"
            )

        # Validate required top-level fields in boxAppSettings
        if "clientID" not in self.boxAppSettings:
            raise ValueError("boxAppSettings missing required 'clientID' field")
        if "clientSecret" not in self.boxAppSettings:
            raise ValueError("boxAppSettings missing required 'clientSecret' field")
        if "appAuth" not in self.boxAppSettings:
            raise ValueError("boxAppSettings missing required 'appAuth' field")

        # Validate appAuth structure
        app_auth = self.boxAppSettings["appAuth"]
        if not isinstance(app_auth, dict):
            raise ValueError(
                f"boxAppSettings.appAuth must be a dict, got {type(app_auth).__name__}"
            )

        # Validate required fields in appAuth
        if "privateKey" not in app_auth:
            raise ValueError(
                "boxAppSettings.appAuth missing required 'privateKey' field"
            )
        if "publicKeyID" not in app_auth:
            raise ValueError(
                "boxAppSettings.appAuth missing required 'publicKeyID' field"
            )

    @property
    def client_id(self) -> str:
        return self.boxAppSettings["clientID"]

    @property
    def client_secret(self) -> str:
        return self.boxAppSettings["clientSecret"]

    @property
    def private_key(self) -> str:
        return self.boxAppSettings["appAuth"]["privateKey"]

    @property
    def passphrase(self) -> str | None:
        return self.boxAppSettings["appAuth"].get("passphrase")

    @property
    def public_key_id(self) -> str:
        return self.boxAppSettings["appAuth"]["publicKeyID"]


def get_box_jwt_config() -> BoxJWTConfig:
    """Get Box JWT config from KV store."""
    try:
        creds_str = str(get_kv_store().load(KV_BOX_JWT_CONFIG))
        return BoxJWTConfig(**json.loads(creds_str))
    except KvKeyNotFoundError:
        raise KvKeyNotFoundError("Box JWT config not found in KV store")


def upsert_box_jwt_config(jwt_config: BoxJWTConfig) -> None:
    """Store Box JWT config in KV store (encrypted)."""
    get_kv_store().store(
        KV_BOX_JWT_CONFIG,
        jwt_config.model_dump_json(),
        encrypt=True,
    )


def delete_box_jwt_config() -> None:
    """Delete Box JWT config from KV store."""
    get_kv_store().delete(KV_BOX_JWT_CONFIG)


def build_box_jwt_creds(
    primary_admin_user_id: str | None = None,
    name: str | None = None,
) -> CredentialBase:
    """Build CredentialBase from Box JWT config stored in KV store.

    Note: JWT config (including private key) is stored encrypted in KV store,
    not in credential_json to avoid duplicating sensitive data in admin_public credentials.
    """
    # Don't include JWT config in credential_json - it's stored encrypted in KV store
    # The connector will load it from KV store when needed
    credential_dict: dict[str, Any] = {}
    if primary_admin_user_id:
        credential_dict[DB_CREDENTIALS_PRIMARY_ADMIN_USER_ID] = primary_admin_user_id

    credential_dict[DB_CREDENTIALS_AUTHENTICATION_METHOD] = (
        BOX_AUTHENTICATION_METHOD_UPLOADED
    )

    return CredentialBase(
        credential_json=credential_dict,
        admin_public=True,
        source=DocumentSource.BOX,
        name=name or "Box JWT (uploaded)",
    )
