"""Plain data the Microsoft connectors share: what an app-only sign-in tells,
the row text and field labels of their capability checks, and what
SharePoint permission sync works on (principals and role assignments from
SharePoint REST, the members of an Entra group from Graph). The office365
objects never leave ``sharepoint_rest``."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class SharepointPrincipal(BaseModel):
    """A user, Entra group or SharePoint group from a role assignment or a site
    group."""

    model_config = ConfigDict(frozen=True)

    principal_type: int
    login_name: str
    title: str
    user_principal_name: str | None = None


class SharepointRoleAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    member: SharepointPrincipal | None
    role_type_kinds: list[int]


class SharepointSecurableKind(str, Enum):
    SITE = "site"
    LIBRARY = "library"
    LIST_ITEM = "list_item"
    PAGE = "page"
    FOLDER = "folder"


class SharepointSecurable(BaseModel):
    """The object whose role assignments to read, within one site."""

    model_config = ConfigDict(frozen=True)

    kind: SharepointSecurableKind
    list_id: str | None = None
    item_id: int | None = None
    # A site page's absolute web URL.
    page_url: str | None = None
    folder_unique_id: str | None = None


class EntraMemberKind(str, Enum):
    USER = "user"
    GROUP = "group"
    UNKNOWN = "unknown"


class EntraMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EntraMemberKind
    id: str
    display_name: str | None = None
    user_principal_name: str | None = None
    mail: str | None = None


class MicrosoftTokenInfo(BaseModel):
    """What an app-only sign-in tells about the app: the token's lifetime,
    the app's name and id from the token's claims, and, for a certificate
    account, the certificate's end date."""

    model_config = ConfigDict(frozen=True)

    expires_in: int | None = None
    app_name: str | None = None
    app_id: str | None = None
    certificate_not_after: datetime | None = None


class MicrosoftRowText(BaseModel):
    """The row text of one outcome of a probe."""

    model_config = ConfigDict(frozen=True)

    summary: str
    description: str


class MicrosoftAccountLabels(BaseModel):
    """The names the connector form gives the account's fields, for lines
    that tell the admin which field to fix."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    directory_id: str
    client_secret: str
    private_key: str
    certificate_password: str

    @classmethod
    def with_prefix(
        cls, prefix: str, *, private_key: str | None = None
    ) -> "MicrosoftAccountLabels":
        return cls(
            client_id=f"{prefix} Client ID",
            directory_id=f"{prefix} Directory ID",
            client_secret=f"{prefix} Client Secret",
            private_key=private_key or f"{prefix} Private Key",
            certificate_password=f"{prefix} Certificate Password",
        )


class MicrosoftSignIn(BaseModel):
    """What a passing sign-in check shows: its line, and caveats."""

    summary: str
    description: str | None = None
    caveats: list[str] = []


class AccessTokenClaims(BaseModel):
    """The claims of an app-only access token that name the app."""

    model_config = ConfigDict(extra="ignore")

    app_displayname: str | None = None
    appid: str | None = None
    azp: str | None = None
