from typing import cast

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.entity_type import KGEntityType
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import validate_kg_settings
from onyx.kg.models import KGEntityTypeAttributes
from onyx.kg.models import KGEntityTypeClassificationInfo
from onyx.kg.models import KGEntityTypeDefinition
from onyx.kg.models import KGGroundingType


def get_default_entity_types(vendor_name: str) -> dict[str, KGEntityTypeDefinition]:
    return {
        "LINEAR": KGEntityTypeDefinition(
            description="A formal Linear ticket about a product issue or improvement request.",
            attributes=KGEntityTypeAttributes(
                metadata_attributes={
                    "team": "team",
                    "state": "state",
                    "priority": "priority",
                    "created_at": "created_at",
                    "completed_at": "completed_at",
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
                metadata_attributes={
                    "issuetype": "subtype",
                    "key": "key",
                    "parent": "parent",
                    "status": "status",
                    "priority": "priority",
                    "reporter": "creator",
                    "project_name": "project",
                    "created": "created_at",
                    "updated": "updated",
                },
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.JIRA,
        ),
        "GITHUB_PR": KGEntityTypeDefinition(
            description="A formal engineering request to merge proposed changes into the codebase.",
            attributes=KGEntityTypeAttributes(
                metadata_attributes={
                    "repo": "repository",
                    "state": "state",
                    "num_commits": "num_commits",
                    "num_files_changed": "num_files_changed",
                    "labels": "labels",
                    "merged": "merged",
                    "merged_at": "merged_at",
                    "closed_at": "closed_at",
                    "created_at": "created_at",
                    "updated_at": "updated_at",
                },
                entity_filter_attributes={"object_type": "PullRequest"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GITHUB,
        ),
        "GITHUB_ISSUE": KGEntityTypeDefinition(
            description="A formal engineering ticket about an issue, idea, inquiry, or task.",
            attributes=KGEntityTypeAttributes(
                metadata_attributes={
                    "repo": "repository",
                    "state": "state",
                    "labels": "labels",
                    "closed_at": "closed_at",
                    "created_at": "created_at",
                    "updated_at": "updated_at",
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
        "GONG": KGEntityTypeDefinition(
            description=(
                f"A phone call transcript between us ({vendor_name}) "
                "and another account or individuals, or an internal meeting."
            ),
            attributes=KGEntityTypeAttributes(),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GONG,
        ),
        "GOOGLE_DRIVE": KGEntityTypeDefinition(
            description="A Google Drive document.",
            attributes=KGEntityTypeAttributes(),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GOOGLE_DRIVE,
        ),
        "GMAIL": KGEntityTypeDefinition(
            description="An email.",
            attributes=KGEntityTypeAttributes(),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.GMAIL,
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
                metadata_attributes={
                    "name": "name",
                    "stage_name": "stage",
                    "type": "type",
                    "amount": "amount",
                    "fiscal_year": "fiscal_year",
                    "fiscal_quarter": "fiscal_quarter",
                    "is_closed": "is_closed",
                    "close_date": "close_date",
                    "probability": "probability",
                    "created_date": "created_at",
                    "last_modified_date": "updated_at",
                },
                entity_filter_attributes={"object_type": "Opportunity"},
            ),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SALESFORCE,
        ),
        "SLACK": KGEntityTypeDefinition(
            description="A Slack conversation.",
            attributes=KGEntityTypeAttributes(),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.SLACK,
        ),
        "WEB": KGEntityTypeDefinition(
            description="A web page.",
            attributes=KGEntityTypeAttributes(),
            grounding=KGGroundingType.GROUNDED,
            grounded_source_name=DocumentSource.WEB,
        ),
        "VENDOR": KGEntityTypeDefinition(
            description=f"The Vendor {vendor_name}, 'us'",
            grounding=KGGroundingType.GROUNDED,
            active=False,
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
            attributes=entity_type_definition.attributes.model_dump(),
            grounding=entity_type_definition.grounding,
            grounded_source_name=grounded_source_name,
            active=False,
        )
        db_session.add(kg_entity_type)
    db_session.commit()
