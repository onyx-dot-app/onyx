from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.kg.models import KGDefaultEntityDefinition
from onyx.kg.models import KGGroundingType


class KGDefaultPrimaryGroundedEntityDefinitions(BaseModel):

    LINEAR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A formal Linear ticket about a product issue or improvement request.",
        attributes={
            "metadata_attributes": {
                "team": "",
                "state": "",
                "priority": "",
                "created_at": "",
                "completed_at": "",
            },
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.LINEAR,
    )

    JIRA__EPIC: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A formal Jira ticket describing large bodies of work that can be broken down into "
            "a number of smaller Jira Tasks, Stories, or Bugs."
        ),
        attributes={
            "metadata_attributes": {
                "status": "",
                "priority": "",
                "reporter": "",
                "project_name": "",
                "created": "",
                "updated": "",
            },
            "entity_filter_attributes": {"issuetype": "Epic"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.JIRA,
    )

    JIRA__STORY: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "Also called 'user stories', these are Jira tickets describing short requirements or requests "
            "written from the perspective of the end user."
        ),
        attributes={
            "metadata_attributes": {
                "status": "",
                "priority": "",
                "reporter": "",
                "project_name": "",
                "created": "",
                "updated": "",
            },
            "entity_filter_attributes": {"issuetype": "Story"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.JIRA,
    )

    JIRA__BUG: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=("A Jira ticket describing a bug."),
        attributes={
            "metadata_attributes": {
                "status": "",
                "priority": "",
                "reporter": "",
                "project_name": "",
                "created": "",
                "updated": "",
            },
            "entity_filter_attributes": {"issuetype": "Bug"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.JIRA,
    )

    JIRA__TASK: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=("A Jira ticket describing a unit of work."),
        attributes={
            "metadata_attributes": {
                "status": "",
                "priority": "",
                "reporter": "",
                "project_name": "",
                "created": "",
                "updated": "",
            },
            "entity_filter_attributes": {"issuetype": "Task"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.JIRA,
    )

    JIRA__SUBTASK: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=("A Jira ticket describing a sub-unit of work."),
        attributes={
            "metadata_attributes": {
                "status": "",
                "priority": "",
                "reporter": "",
                "project_name": "",
                "created": "",
                "updated": "",
            },
            "entity_filter_attributes": {"issuetype": "Sub-task"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.JIRA,
    )

    GITHUB__PR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="Our (---vendor_name---) Engineering PRs describing what was actually implemented.",
        attributes={
            "metadata_attributes": {
                "repo": "",
                "state": "",
                "num_commits": "",
                "num_files_changed": "",
                "labels": "",
                "merged": "",
                "merged_at": "",
                "closed_at": "",
                "created_at": "",
                "updated_at": "",
            },
            "entity_filter_attributes": {"object_type": "PullRequest"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.GITHUB,
    )

    GITHUB__ISSUE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="Our (---vendor_name---) Engineering issues describing what needs to be implemented.",
        attributes={
            "metadata_attributes": {
                "repo": "",
                "state": "",
                "labels": "",
                "closed_at": "",
                "created_at": "",
                "updated_at": "",
            },
            "entity_filter_attributes": {"object_type": "Issue"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.GITHUB,
    )

    FIREFLIES: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A phone call transcript between us (---vendor_name---) "
            "and another account or individuals, or an internal meeting."
        ),
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {
                "customer": {
                    "extraction": True,
                    "description": "a call with representatives of one or more customers prospects",
                },
                "internal": {
                    "extraction": True,
                    "description": "a call between employees of the vendor's company (a vendor-internal call)",
                },
                "interview": {
                    "extraction": True,
                    "description": (
                        "a call with an individual who is interviewed or is discussing potential employment with the vendor"
                    ),
                },
                "other": {
                    "extraction": True,
                    "description": (
                        "a call with representatives of companies having a different reason for the call "
                        "(investment, partnering, etc.)"
                    ),
                },
            },
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.FIREFLIES,
    )

    GONG: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A phone call transcript between us (---vendor_name---) "
            "and another account or individuals, or an internal meeting."
        ),
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.GONG,
    )

    GOOGLE_DRIVE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A Google Drive document.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.GOOGLE_DRIVE,
    )

    GMAIL: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="An email.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.GMAIL,
    )

    ACCOUNT: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A company that was, is, or potentially could be a customer of the vendor "
            "('us, ---vendor_name---'). Note that ---vendor_name--- can never be an ACCOUNT."
        ),
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {"object_type": "Account"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.SALESFORCE,
    )

    OPPORTUNITY: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A sales opportunity.",
        attributes={
            "metadata_attributes": {
                "name": "",
                "stage_name": "",
                "type": "",
                "amount": "",
                "fiscal_year": "",
                "fiscal_quarter": "",
                "is_closed": "",
                "close_date": "",
                "probability": "",
                "created_date": "",
                "last_modified_date": "",
            },
            "entity_filter_attributes": {"object_type": "Opportunity"},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.SALESFORCE,
    )

    SLACK: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A Slack conversation.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.SLACK,
    )

    WEB: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="A web page.",
        attributes={
            "metadata_attributes": {},
            "entity_filter_attributes": {},
            "classification_attributes": {},
        },
        grounding=KGGroundingType.GROUNDED,
        grounded_source_name=DocumentSource.WEB,
    )


class KGDefaultAccountEmployeeDefinitions(BaseModel):

    VENDOR: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description="The Vendor ---vendor_name---, 'us'",
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )

    ACCOUNT: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A company that was, is, or potentially could be a customer of the vendor "
            "('us, ---vendor_name---'). Note that ---vendor_name--- can never be an ACCOUNT."
        ),
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )

    EMPLOYEE: KGDefaultEntityDefinition = KGDefaultEntityDefinition(
        description=(
            "A person who speaks on behalf of 'our' company (the VENDOR ---vendor_name---), "
            "NOT of another account. Therefore, employees of other companies "
            "are NOT included here. If in doubt, do NOT extract."
        ),
        grounding=KGGroundingType.GROUNDED,
        active=False,
        grounded_source_name=None,
    )
