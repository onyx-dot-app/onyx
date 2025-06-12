from collections.abc import Generator

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.entity_type import KGEntityType
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import validate_kg_settings
from onyx.kg.models import KGDefaultEntityDefinition
from onyx.kg.models import KGGroundingType


def _get_default_entity_types(vendor_name: str) -> dict[str, KGDefaultEntityDefinition]:
    return {
        "LINEAR": KGDefaultEntityDefinition(
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
        ),
        "JIRA-EPIC": KGDefaultEntityDefinition(
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
        ),
        "JIRA-STORY": KGDefaultEntityDefinition(
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
        ),
        "JIRA-BUG": KGDefaultEntityDefinition(
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
        ),
        "JIRA-TASK": KGDefaultEntityDefinition(
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
        ),
        "JIRA-SUBTASK": KGDefaultEntityDefinition(
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
        ),
        "GITHUB-PR": KGDefaultEntityDefinition(
            description=f"Our ({vendor_name}) Engineering PRs describing what was actually implemented.",
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
        ),
        "GITHUB-ISSUE": KGDefaultEntityDefinition(
            description=f"Our ({vendor_name}) Engineering issues describing what needs to be implemented.",
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
        ),
        "FIREFLIES": KGDefaultEntityDefinition(
            description=(
                f"A phone call transcript between us ({vendor_name}) "
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
        ),
        "GONG": KGDefaultEntityDefinition(
            description=(
                f"A phone call transcript between us ({vendor_name}) "
                "and another account or individuals, or an internal meeting."
            ),
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GONG,
        ),
        "GOOGLE_DRIVE": KGDefaultEntityDefinition(
            description="A Google Drive document.",
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GOOGLE_DRIVE,
        ),
        "GMAIL": KGDefaultEntityDefinition(
            description="An email.",
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GMAIL,
        ),
        "ACCOUNT": KGDefaultEntityDefinition(
            description=(
                "A company that was, is, or potentially could be a customer of the vendor "
                f"('us, {vendor_name}'). Note that {vendor_name} can never be an ACCOUNT."
            ),
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {"object_type": "Account"},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SALESFORCE,
        ),
        "OPPORTUNITY": KGDefaultEntityDefinition(
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
        ),
        "SLACK": KGDefaultEntityDefinition(
            description="A Slack conversation.",
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SLACK,
        ),
        "WEB": KGDefaultEntityDefinition(
            description="A web page.",
            attributes={
                "metadata_attributes": {},
                "entity_filter_attributes": {},
                "classification_attributes": {},
            },
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.WEB,
        ),
        "VENDOR": KGDefaultEntityDefinition(
            description=f"The Vendor {vendor_name}, 'us'",
            grounding=KGGroundingType.GROUNDED,
            active=False,
            grounded_source_name=None,
        ),
        "EMPLOYEE": KGDefaultEntityDefinition(
            description=(
                f"A person who speaks on behalf of 'our' company (the VENDOR {vendor_name}), "
                "NOT of another account. Therefore, employees of other companies "
                "are NOT included here. If in doubt, do NOT extract."
            ),
            grounding=KGGroundingType.GROUNDED,
            active=False,
            grounded_source_name=None,
        ),
    }


def _generate_non_existing_entity_types(
    existing_entity_types: dict[str, KGEntityType],
    vendor_name: str,
) -> Generator[KGEntityType]:
    default_entity_types = _get_default_entity_types(vendor_name=vendor_name)

    for default_entity_name, default_entity_type in default_entity_types.items():
        if default_entity_name not in existing_entity_types:
            grounded_source_name = (
                default_entity_type.grounded_source_name.value
                if default_entity_type.grounded_source_name
                else None
            )
            yield KGEntityType(
                id_name=default_entity_name,
                description=default_entity_type.description,
                attributes=default_entity_type.attributes,
                grounding=default_entity_type.grounding,
                grounded_source_name=grounded_source_name,
                active=False,
            )


def populate_default_entity_types(
    db_session: Session,
) -> list[KGEntityType]:
    """
    Populates the database with the *missing* Entity Types (if any are missing) into the database.
    Returns the *entire* list of Entity Types.
    """

    kg_config_settings = get_kg_config_settings(db_session=db_session)
    validate_kg_settings(kg_config_settings)

    vendor_name = kg_config_settings.KG_VENDOR
    if not vendor_name:
        raise ValueError(
            f"Vendor name must be a non-empty string, instead got {vendor_name=}"
        )

    existing_entity_types = {
        et.id_name: et for et in db_session.query(KGEntityType).all()
    }
    non_existing_entity_types = _generate_non_existing_entity_types(
        existing_entity_types=existing_entity_types,
        vendor_name=vendor_name,
    )

    entity_types = []

    for non_existing_entity_type in non_existing_entity_types:
        db_session.add(non_existing_entity_type)
        entity_types.append(non_existing_entity_type)

    db_session.commit()

    entity_types.extend(existing_entity_types.values())

    return entity_types
