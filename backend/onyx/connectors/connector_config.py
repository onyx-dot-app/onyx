from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class CredentialBinding(BaseModel):
    """The config fields whose valid values depend on the account behind the
    credential, e.g. a site URL, a cloud vs. data center flag, or a national-cloud
    host. A connector config inherits its binding model, so the stored config
    stays flat. Validated on its own from a full config, it ignores the other keys.
    """

    def validate_credential(
        self,
        credential_json: dict[str, Any],  # noqa: ARG002
    ) -> None:
        """Raises ``ConnectorValidationError`` if the credential cannot be used
        with these values. Only checks what the credential itself records; most
        credentials record nothing, so the default accepts every credential."""


class BaseUrlCredentialBinding(CredentialBinding):
    """For sources whose only credential-bound field is the site URL."""

    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


def normalize_realm(realm: str) -> str:
    """A realm as typed or stored, compared without case, scheme or a trailing
    slash."""
    cleaned = realm.strip().lower()
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    return cleaned.rstrip("/")


class RealmCredentialBinding(CredentialBinding):
    """For sources whose account records its realm (site, host or subdomain) in
    the credential under ``REALM_KEY``. The config holds the same key, and the
    credential must record the same realm. An empty config realm accepts every
    credential; a credential without one counts as ``DEFAULT_REALM``.

    The connector keeps reading the realm from the credential.
    """

    REALM_KEY: ClassVar[str]
    DEFAULT_REALM: ClassVar[str | None] = None

    @classmethod
    def normalize(cls, realm: str) -> str:
        return normalize_realm(realm)

    def validate_credential(self, credential_json: dict[str, Any]) -> None:
        configured = self.model_dump().get(self.REALM_KEY)
        if not isinstance(configured, str) or not configured.strip():
            return
        stored = credential_json.get(self.REALM_KEY)
        account_realm = (
            stored if isinstance(stored, str) and stored.strip() else self.DEFAULT_REALM
        )
        if account_realm is None:
            return
        if self.normalize(configured) != self.normalize(account_realm):
            raise ConnectorValidationError(
                f"This account works at {account_realm}, not {configured}."
            )


class ConnectorConfig(BaseModel):
    """Typed shape of a connector's ``connector_specific_config``.

    Each field mirrors one ``__init__`` kwarg of the connector class, with the
    same name, default, and required-ness. ``test_connector_config_models``
    enforces this. Subclasses live in ``<connector>/config.py`` modules, which
    must stay light to import: the registry loads all of them eagerly.
    """

    # extra="forbid" matches the kwargs constructors, where an unknown key is a
    # TypeError. Some configs hold secrets, so errors must not echo input values.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @classmethod
    def credential_binding_class(cls) -> type[CredentialBinding] | None:
        """The most specific binding model this config inherits, if any."""
        return next(
            (
                base
                for base in cls.__mro__
                if issubclass(base, CredentialBinding)
                and not issubclass(base, ConnectorConfig)
            ),
            None,
        )
