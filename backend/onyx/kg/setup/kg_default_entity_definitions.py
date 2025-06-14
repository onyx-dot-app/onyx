from typing import cast

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.entity_type import KGEntityType
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import validate_kg_settings
from onyx.kg.models import KGDefaultEntityDefinition
from onyx.kg.models import KGGroundingType


def get_default_entity_types(vendor_name: str) -> dict[str, KGDefaultEntityDefinition]:
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
                "classification_attributes": {},
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


def populate_missing_default_entity_types__commit(db_session: Session) -> None:
    """
    Populates the database with the missing default entity types.
    """
    kg_config_settings = get_kg_config_settings(db_session=db_session)
    validate_kg_settings(kg_config_settings)

    vendor_name = cast(str, kg_config_settings.KG_VENDOR)

    existing_entity_types = {et.id_name for et in db_session.query(KGEntityType).all()}

    default_entity_types = get_default_entity_types(vendor_name=vendor_name)
    for entity_type_id_name, entity_type_definition in default_entity_types.items():
        if entity_type_id_name in existing_entity_types:
            continue

        grounded_source_name = (
            entity_type_definition.grounded_source_name.value
            if entity_type_definition.grounded_source_name
            else None
        )
        kg_entity_type = KGEntityType(
            id_name=entity_type_id_name,
            description=entity_type_definition.description,
            attributes=entity_type_definition.attributes,
            grounding=entity_type_definition.grounding,
            grounded_source_name=grounded_source_name,
            active=False,
        )
        db_session.add(kg_entity_type)
    db_session.commit()
