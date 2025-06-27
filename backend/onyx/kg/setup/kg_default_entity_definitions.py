from typing import cast

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.entity_type import KGEntityType
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import validate_kg_settings
from onyx.kg.models import KGAttributeEntityOption
from onyx.kg.models import KGAttributeImplicationProperty
from onyx.kg.models import KGAttributeProperty
from onyx.kg.models import KGEntityTypeAttributes
from onyx.kg.models import KGEntityTypeClassificationInfo
from onyx.kg.models import KGEntityTypeDefinition
from onyx.kg.models import KGGroundingType


def get_default_entity_types(vendor_name: str) -> dict[str, KGEntityTypeDefinition]:
    return {
        "LINEAR": KGEntityTypeDefinition(
            description="A formal Linear ticket about a product issue or improvement request.",
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "team": KGAttributeProperty(name="team", keep=True),
                    "state": KGAttributeProperty(name="state", keep=True),
                    "priority": KGAttributeProperty(name="priority", keep=True),
                    "estimate": KGAttributeProperty(name="estimate", keep=True),
                    "created_at": KGAttributeProperty(name="created_at", keep=True),
                    "started_at": KGAttributeProperty(name="started_at", keep=True),
                    "completed_at": KGAttributeProperty(name="completed_at", keep=True),
                    "due_date": KGAttributeProperty(name="due_date", keep=True),
                    "creator": KGAttributeProperty(
                        name="creator",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_creator_of",
                        ),
                    ),
                    "assignee": KGAttributeProperty(
                        name="assignee",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_assignee_of",
                        ),
                    ),
                },
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.LINEAR,
        ),
        "JIRA": KGEntityTypeDefinition(
            description=(
                "A formal Jira ticket about a product issue or improvement request."
            ),
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "issuetype": KGAttributeProperty(name="subtype", keep=True),
                    "status": KGAttributeProperty(name="status", keep=True),
                    "priority": KGAttributeProperty(name="priority", keep=True),
                    "project_name": KGAttributeProperty(name="project", keep=True),
                    "created": KGAttributeProperty(name="created_at", keep=True),
                    "updated": KGAttributeProperty(name="updated_at", keep=True),
                    "resolution_date": KGAttributeProperty(
                        name="completed_at", keep=True
                    ),
                    "duedate": KGAttributeProperty(name="due_date", keep=True),
                    "reporter_email": KGAttributeProperty(
                        name="creator",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_creator_of",
                        ),
                    ),
                    "assignee_email": KGAttributeProperty(
                        name="assignee",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_assignee_of",
                        ),
                    ),
                    # not using implication property as that only captures 1 depth
                    "key": KGAttributeProperty(name="key", keep=True),
                    "parent": KGAttributeProperty(name="parent", keep=True),
                },
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.JIRA,
        ),
        "GITHUB_PR": KGEntityTypeDefinition(
            description="A formal engineering request to merge proposed changes into the codebase.",
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "repo": KGAttributeProperty(name="repository", keep=True),
                    "state": KGAttributeProperty(name="state", keep=True),
                    "num_commits": KGAttributeProperty(name="num_commits", keep=True),
                    "num_files_changed": KGAttributeProperty(
                        name="num_files_changed", keep=True
                    ),
                    "labels": KGAttributeProperty(name="labels", keep=True),
                    "merged": KGAttributeProperty(name="merged", keep=True),
                    "merged_at": KGAttributeProperty(name="merged_at", keep=True),
                    "closed_at": KGAttributeProperty(name="closed_at", keep=True),
                    "created_at": KGAttributeProperty(name="created_at", keep=True),
                    "updated_at": KGAttributeProperty(name="updated_at", keep=True),
                    "user": KGAttributeProperty(
                        name="creator",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_creator_of",
                        ),
                    ),
                    "assignees": KGAttributeProperty(
                        name="assignees",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_assignee_of",
                        ),
                    ),
                },
                entity_filter_attributes={"object_type": "PullRequest"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GITHUB,
        ),
        "GITHUB_ISSUE": KGEntityTypeDefinition(
            description="A formal engineering ticket about an issue, idea, inquiry, or task.",
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "repo": KGAttributeProperty(name="repository", keep=True),
                    "state": KGAttributeProperty(name="state", keep=True),
                    "labels": KGAttributeProperty(name="labels", keep=True),
                    "closed_at": KGAttributeProperty(name="closed_at", keep=True),
                    "created_at": KGAttributeProperty(name="created_at", keep=True),
                    "updated_at": KGAttributeProperty(name="updated_at", keep=True),
                    "user": KGAttributeProperty(
                        name="creator",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_creator_of",
                        ),
                    ),
                    "assignees": KGAttributeProperty(
                        name="assignees",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type=KGAttributeEntityOption.FROM_EMAIL,
                            implied_relationship_name="is_assignee_of",
                        ),
                    ),
                },
                entity_filter_attributes={"object_type": "Issue"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GITHUB,
        ),
        "FIREFLIES": KGEntityTypeDefinition(
            description=(
                f"A phone call transcript between us ({vendor_name}) "
                "and another account or individuals, or an internal meeting."
            ),
            attributes=KGEntityTypeAttributes(
                classification_attributes={
                    "customer": KGEntityTypeClassificationInfo(
                        extraction=True,
                        description="a call with representatives of one or more customers prospects",
                    ),
                    "internal": KGEntityTypeClassificationInfo(
                        extraction=True,
                        description="a call between employees of the vendor's company (a vendor-internal call)",
                    ),
                    "interview": KGEntityTypeClassificationInfo(
                        extraction=True,
                        description=(
                            "a call with an individual who is interviewed or is discussing potential employment with the vendor"
                        ),
                    ),
                    "other": KGEntityTypeClassificationInfo(
                        extraction=True,
                        description=(
                            "a call with representatives of companies having a different reason for the call "
                            "(investment, partnering, etc.)"
                        ),
                    ),
                },
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.FIREFLIES,
        ),
        "ACCOUNT": KGEntityTypeDefinition(
            description=(
                "A company that was, is, or potentially could be a customer of the vendor "
                f"('us, {vendor_name}'). Note that {vendor_name} can never be an ACCOUNT."
            ),
            attributes=KGEntityTypeAttributes(
                entity_filter_attributes={"object_type": "Account"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SALESFORCE,
        ),
        "OPPORTUNITY": KGEntityTypeDefinition(
            description="A sales opportunity.",
            attributes=KGEntityTypeAttributes(
                metadata_attribute_conversion={
                    "name": KGAttributeProperty(name="name", keep=True),
                    "stage_name": KGAttributeProperty(name="stage", keep=True),
                    "type": KGAttributeProperty(name="type", keep=True),
                    "amount": KGAttributeProperty(name="amount", keep=True),
                    "fiscal_year": KGAttributeProperty(name="fiscal_year", keep=True),
                    "fiscal_quarter": KGAttributeProperty(
                        name="fiscal_quarter", keep=True
                    ),
                    "is_closed": KGAttributeProperty(name="is_closed", keep=True),
                    "close_date": KGAttributeProperty(name="close_date", keep=True),
                    "probability": KGAttributeProperty(
                        name="close_probability", keep=True
                    ),
                    "created_date": KGAttributeProperty(name="created_at", keep=True),
                    "last_modified_date": KGAttributeProperty(
                        name="updated_at", keep=True
                    ),
                    "account": KGAttributeProperty(
                        name="account",
                        keep=False,
                        implication_property=KGAttributeImplicationProperty(
                            implied_entity_type="ACCOUNT",
                            implied_relationship_name="is_account_of",
                        ),
                    ),
                },
                entity_filter_attributes={"object_type": "Opportunity"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SALESFORCE,
        ),
        "VENDOR": KGEntityTypeDefinition(
            description=f"The Vendor {vendor_name}, 'us'",
            grounding=KGGroundingType.GROUNDED,
            active=True,
            grounded_source_name=None,
        ),
        "EMPLOYEE": KGEntityTypeDefinition(
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
    kg_config_settings = get_kg_config_settings()
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
            attributes=entity_type_definition.attributes.model_dump(),
            grounding=entity_type_definition.grounding,
            grounded_source_name=grounded_source_name,
            active=entity_type_definition.active,
        )
        db_session.add(kg_entity_type)
    db_session.commit()
