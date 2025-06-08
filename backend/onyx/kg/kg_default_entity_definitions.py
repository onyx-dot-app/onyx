from pydantic import BaseModel

from onyx.kg.models import KGDefaultEntityDefinition
from onyx.kg.models import KGGroundingType


class KGDefaultPrimaryGroundedEntityDefinitions(BaseModel):

    LINEAR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A formal ticket about a product issue or improvement request.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="linear",
    )

    GITHUB_PR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="Our (---vendor_name---) Engineering PRs describing what was actually implemented.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="github",
    )

    FIREFLIES: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A phone call transcript between us (---vendor_name---) \
and another account or individuals, or an internal meeting.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="fireflies",
    )

    GONG: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A phone call transcript between us (---vendor_name---) \
and another account or individuals, or an internal meeting.",
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="gong",
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

    ACCOUNT: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A company that was, is, or potentially could be a customer of the vendor \
('us, ---vendor_name---'). Note that ---vendor_name--- can never be an ACCOUNT.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {"object_type": "Account"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="salesforce",
    )
    OPPORTUNITY: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A sales opportunity.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {"object_type": "Opportunity"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name="salesforce",
    )


class KGDefaultAccountEmployeeDefinitions(BaseModel):

    VENDOR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="The Vendor ---vendor_name---, 'us'",
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )

    ACCOUNT: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A company that was, is, or potentially could be a customer of the vendor \
('us, ---vendor_name---'). Note that ---vendor_name--- can never be an ACCOUNT.",
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )

    EMPLOYEE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A person who speaks on \
behalf of 'our' company (the VENDOR ---vendor_name---), NOT of another account. Therefore, employees of other companies \
are NOT included here. If in doubt, do NOT extract.",
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )
