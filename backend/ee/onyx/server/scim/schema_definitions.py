"""Static SCIM service discovery responses (RFC 7643 §5, §6, §7).

Pre-built at import time — these never change at runtime. Separated from
api.py to keep the endpoint module focused on request handling.
"""

from ee.onyx.server.scim.models import SCIM_GROUP_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimSchemaAttribute
from ee.onyx.server.scim.models import ScimSchemaDefinition
from ee.onyx.server.scim.models import ScimServiceProviderConfig

SERVICE_PROVIDER_CONFIG = ScimServiceProviderConfig()

USER_RESOURCE_TYPE = ScimResourceType.model_validate(
    {
        "id": "User",
        "name": "User",
        "endpoint": "/scim/v2/Users",
        "description": "SCIM User resource",
        "schema": SCIM_USER_SCHEMA,
    }
)

GROUP_RESOURCE_TYPE = ScimResourceType.model_validate(
    {
        "id": "Group",
        "name": "Group",
        "endpoint": "/scim/v2/Groups",
        "description": "SCIM Group resource",
        "schema": SCIM_GROUP_SCHEMA,
    }
)

USER_SCHEMA_DEF = ScimSchemaDefinition(
    id=SCIM_USER_SCHEMA,
    name="User",
    description="SCIM core User schema",
    attributes=[
        ScimSchemaAttribute(
            name="userName",
            type="string",
            required=True,
            uniqueness="server",
            description="Unique identifier for the user, typically an email address.",
        ),
        ScimSchemaAttribute(
            name="name",
            type="complex",
            description="The components of the user's name.",
            subAttributes=[
                ScimSchemaAttribute(
                    name="givenName",
                    type="string",
                    description="The user's first name.",
                ),
                ScimSchemaAttribute(
                    name="familyName",
                    type="string",
                    description="The user's last name.",
                ),
                ScimSchemaAttribute(
                    name="formatted",
                    type="string",
                    description="The full name, including all middle names and titles.",
                ),
            ],
        ),
        ScimSchemaAttribute(
            name="emails",
            type="complex",
            multiValued=True,
            description="Email addresses for the user.",
            subAttributes=[
                ScimSchemaAttribute(
                    name="value",
                    type="string",
                    description="Email address value.",
                ),
                ScimSchemaAttribute(
                    name="type",
                    type="string",
                    description="Label for this email (e.g. 'work').",
                ),
                ScimSchemaAttribute(
                    name="primary",
                    type="boolean",
                    description="Whether this is the primary email.",
                ),
            ],
        ),
        ScimSchemaAttribute(
            name="active",
            type="boolean",
            description="Whether the user account is active.",
        ),
        ScimSchemaAttribute(
            name="externalId",
            type="string",
            description="Identifier from the provisioning client (IdP).",
            caseExact=True,
        ),
    ],
)

GROUP_SCHEMA_DEF = ScimSchemaDefinition(
    id=SCIM_GROUP_SCHEMA,
    name="Group",
    description="SCIM core Group schema",
    attributes=[
        ScimSchemaAttribute(
            name="displayName",
            type="string",
            required=True,
            description="Human-readable name for the group.",
        ),
        ScimSchemaAttribute(
            name="members",
            type="complex",
            multiValued=True,
            description="Members of the group.",
            subAttributes=[
                ScimSchemaAttribute(
                    name="value",
                    type="string",
                    description="User ID of the group member.",
                ),
                ScimSchemaAttribute(
                    name="display",
                    type="string",
                    mutability="readOnly",
                    description="Display name of the group member.",
                ),
            ],
        ),
        ScimSchemaAttribute(
            name="externalId",
            type="string",
            description="Identifier from the provisioning client (IdP).",
            caseExact=True,
        ),
    ],
)
