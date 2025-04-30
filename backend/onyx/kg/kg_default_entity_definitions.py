from pydantic import BaseModel

from onyx.configs.kg_configs import KG_VENDOR
from onyx.kg.models import KGDefaultEntityDefinition
from onyx.kg.models import KGGroundingType


class KGDefaultPrimaryGroundedEntityDefinitions(BaseModel):

    LINEAR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A formal ticket about a product issue or improvement request.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="linear",
    )

    FIREFLIES: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=f"A phone call transcript between us ({KG_VENDOR}) \
and another account or individuals, or an internal meeting.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="fireflies",
    )

    GONG: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=f"A phone call transcript between us ({KG_VENDOR}) and another \
account or individuals, or an internal meeting.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="gong",
    )

    SLACK: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A Slack conversation.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="slack",
    )

    WEB: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A web page.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="web",
    )

    GOOGLE_DRIVE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A Google Drive document.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="google_drive",
    )

    GMAIL: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="An email.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="gmail",
    )

    JIRA: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A formal JIRA ticket about a product issue or improvement request.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="jira",
    )


class KGDefaultAccountEmployeeDefinitions(BaseModel):
    # Not an actual primary grounded entity type, but convenient to include here.
    VENDOR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=f"The Vendor {KG_VENDOR}, 'us'",
        grounding=KGGroundingType.GROUNDED,
        active=True,
        grounded_source_name=None,
    )

    ACCOUNT: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=f"A company that could potentially be or is or was a customer of the vendor \
('us, {KG_VENDOR}'). Note that {KG_VENDOR} can never be an ACCOUNT.",
        grounding=KGGroundingType.GROUNDED,
        active=True,
        grounded_source_name=None,
        # If grounded_source is None, the domain in email addresses will be used. If grounded source is specified,
        # the grounded source name will be used and the domains in email addresses will be matched to Accounts
    )

    EMPLOYEE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=f"A person who speaks on \
behalf of 'our' company (the VENDOR {KG_VENDOR}), NOT of another account. Therefore, employees of other companies \
are NOT included here. If in doubt, do NOT extract.",
        grounding=KGGroundingType.GROUNDED,
        active=True,
        grounded_source_name=None,
        # The email address sans domain will be used to identify the employee.
    )
