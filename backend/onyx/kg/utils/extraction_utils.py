import re
from collections import defaultdict

from onyx.configs.constants import OnyxCallTypes
from onyx.configs.kg_configs import KG_METADATA_TRACKING_THRESHOLD
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.db.kg_config import KGConfigSettings
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent
from onyx.kg.models import (
    KGDocumentClassificationPrompt,
)
from onyx.kg.models import KGDocumentEntitiesRelationshipsAttributes
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.models import MetadataTrackInfo
from onyx.kg.models import MetadataTrackType
from onyx.kg.utils.formatting_utils import generalize_entities
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.prompts.kg_prompts import CALL_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import CALL_DOCUMENT_CLASSIFICATION_PROMPT
from onyx.prompts.kg_prompts import GENERAL_CHUNK_PREPROCESSING_PROMPT


def _update_implied_entities_relationships(
    kg_core_document_id_name: str,
    owner_list: list[str],
    implied_entities: set[str],
    implied_relationships: set[str],
    company_participant_emails: set[str],
    account_participant_emails: set[str],
    relationship_type: str,
    kg_config_settings: KGConfigSettings,
    converted_relationships_to_attributes: dict[str, list[str]],
) -> tuple[set[str], set[str], set[str], set[str], dict[str, list[str]]]:

    for owner in owner_list or []:

        if not is_email(owner):
            converted_relationships_to_attributes[relationship_type].append(owner)
            continue

        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
        ) = kg_process_person(
            owner,
            kg_core_document_id_name,
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
            relationship_type,
            kg_config_settings,
        )

    return (
        implied_entities,
        implied_relationships,
        company_participant_emails,
        account_participant_emails,
        converted_relationships_to_attributes,
    )


def kg_document_entities_relationships_attribute_generation(
    document: Document,
    doc_metadata: KGEnhancedDocumentMetadata,
    active_entities: list[str],
    kg_config_settings: KGConfigSettings,
) -> KGDocumentEntitiesRelationshipsAttributes:
    """
    Generate entities, relationships, and attributes for a document.
    """

    # Get document entity type from the KGEnhancedDocumentMetadata
    document_entity_type = doc_metadata.entity_type
    assert document_entity_type is not None

    # Get additional document attributes from the KGEnhancedDocumentMetadata
    document_attributes = doc_metadata.document_attributes

    implied_entities: set[str] = set()
    implied_relationships: set[str] = (
        set()
    )  # 'Relationships' that will be captured as KG relationships
    converted_relationships_to_attributes: dict[str, list[str]] = defaultdict(
        list
    )  # 'Relationships' that will be captured as KG entity attributes

    converted_attributes_to_relationships: set[str] = (
        set()
    )  # Attributes that should be captures as entities and then relationships (Account = ...)

    company_participant_emails: set[str] = (
        set()
    )  # Quantity needed for call processing - participants from vendor
    account_participant_emails: set[str] = (
        set()
    )  # Quantity needed for call processing - external participants

    # Chunk treatment variables

    document_is_from_call = document_entity_type.lower() in [
        call_type.value.lower() for call_type in OnyxCallTypes
    ]

    # Get core entity

    document_id = document.id
    primary_owners = document.primary_owners
    secondary_owners = document.secondary_owners

    with get_session_with_current_tenant() as db_session:
        kg_core_document = get_kg_entity_by_document(db_session, document_id)

    if kg_core_document:
        kg_core_document_id_name = kg_core_document.id_name
    else:
        kg_core_document_id_name = make_entity_id(document_entity_type, document_id)

    # Get implied entities and relationships from primary/secondary owners

    if document_is_from_call:
        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
            converted_relationships_to_attributes,
        ) = _update_implied_entities_relationships(
            kg_core_document_id_name,
            owner_list=(primary_owners or []) + (secondary_owners or []),
            implied_entities=implied_entities,
            implied_relationships=implied_relationships,
            company_participant_emails=company_participant_emails,
            account_participant_emails=account_participant_emails,
            relationship_type="participates_in",
            kg_config_settings=kg_config_settings,
            converted_relationships_to_attributes=converted_relationships_to_attributes,
        )
    else:
        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
            converted_relationships_to_attributes,
        ) = _update_implied_entities_relationships(
            kg_core_document_id_name,
            owner_list=primary_owners or [],
            implied_entities=implied_entities,
            implied_relationships=implied_relationships,
            company_participant_emails=company_participant_emails,
            account_participant_emails=account_participant_emails,
            relationship_type="leads",
            kg_config_settings=kg_config_settings,
            converted_relationships_to_attributes=converted_relationships_to_attributes,
        )

        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
            converted_relationships_to_attributes,
        ) = _update_implied_entities_relationships(
            kg_core_document_id_name,
            owner_list=secondary_owners or [],
            implied_entities=implied_entities,
            implied_relationships=implied_relationships,
            company_participant_emails=company_participant_emails,
            account_participant_emails=account_participant_emails,
            relationship_type="participates_in",
            kg_config_settings=kg_config_settings,
            converted_relationships_to_attributes=converted_relationships_to_attributes,
        )

    if document_attributes is not None:
        cleaned_document_attributes = document_attributes.copy()
        for attribute, value in document_attributes.items():
            if attribute.lower() in [x.lower() for x in active_entities]:
                converted_attributes_to_relationships.add(attribute)
                if isinstance(value, str):
                    implied_entity = make_entity_id(attribute, value)
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        make_relationship_id(
                            implied_entity,
                            f"is_{attribute}_of",
                            kg_core_document_id_name,
                        )
                    )

                    implied_entity = make_entity_id(attribute, "*")
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        make_relationship_id(
                            implied_entity,
                            f"is_{attribute}_of",
                            kg_core_document_id_name,
                        )
                    )
                    implied_relationships.add(
                        make_relationship_id(
                            implied_entity,
                            f"is_{attribute}_of",
                            make_entity_id(document_entity_type, "*"),
                        )
                    )

                    implied_entity = make_entity_id(attribute, value)
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        make_relationship_id(
                            implied_entity,
                            f"is_{attribute}_of",
                            make_entity_id(document_entity_type, "*"),
                        )
                    )

                    cleaned_document_attributes.pop(attribute)

                elif isinstance(value, list):
                    for item in value:
                        implied_entity = make_entity_id(attribute, item)
                        implied_entities.add(implied_entity)
                        implied_relationships.add(
                            make_relationship_id(
                                implied_entity,
                                f"is_{attribute}_of",
                                kg_core_document_id_name,
                            )
                        )
                        cleaned_document_attributes.pop(attribute)
            if attribute.lower().endswith("_id") or attribute.endswith("Id"):
                cleaned_document_attributes.pop(attribute)
    else:
        cleaned_document_attributes = None

    return KGDocumentEntitiesRelationshipsAttributes(
        kg_core_document_id_name=kg_core_document_id_name,
        implied_entities=implied_entities,
        implied_relationships=implied_relationships,
        company_participant_emails=company_participant_emails,
        account_participant_emails=account_participant_emails,
        converted_relationships_to_attributes=converted_relationships_to_attributes,
        converted_attributes_to_relationships=converted_attributes_to_relationships,
        document_attributes=cleaned_document_attributes,
    )


def _prepare_llm_document_content_call(
    document_classification_content: KGClassificationContent,
    category_list: str,
    category_definition_string: str,
    kg_config_settings: KGConfigSettings,
) -> KGDocumentClassificationPrompt:
    """
    Calls - prepare prompt for the LLM classification.
    """

    prompt = CALL_DOCUMENT_CLASSIFICATION_PROMPT.format(
        beginning_of_call_content=document_classification_content.classification_content,
        category_list=category_list,
        category_options=category_definition_string,
        vendor=kg_config_settings.KG_VENDOR,
    )

    return KGDocumentClassificationPrompt(
        llm_prompt=prompt,
    )


def kg_process_person(
    person: str,
    core_document_id_name: str,
    implied_entities: set[str],
    implied_relationships: set[str],
    company_participant_emails: set[str],
    account_participant_emails: set[str],
    relationship_type: str,
    kg_config_settings: KGConfigSettings,
) -> tuple[set[str], set[str], set[str], set[str]]:
    """
    Process a single owner and return updated sets with entities and relationships.

    Returns:
        tuple containing (implied_entities, implied_relationships, company_participant_emails, account_participant_emails)
    """

    if not kg_config_settings.KG_ENABLED:
        raise ValueError("KG is not enabled")

    assert isinstance(kg_config_settings.KG_IGNORE_EMAIL_DOMAINS, list)

    kg_person = kg_email_processing(person, kg_config_settings)
    if any(
        domain.lower() in kg_person.company.lower()
        for domain in kg_config_settings.KG_IGNORE_EMAIL_DOMAINS
    ):
        return (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
        )

    if kg_person.employee:
        company_participant_emails = company_participant_emails | {
            f"{kg_person.name} -- ({kg_person.company})"
        }
        if kg_person.name not in implied_entities:
            target_general = list(generalize_entities([core_document_id_name]))[0]
            employee_entity = make_entity_id("EMPLOYEE", kg_person.name)
            employee_general = make_entity_id("EMPLOYEE", "*")

            implied_entities.add(employee_entity)
            implied_relationships |= {
                make_relationship_id(
                    employee_entity, relationship_type, core_document_id_name
                ),
                make_relationship_id(
                    employee_entity, relationship_type, target_general
                ),
                make_relationship_id(
                    employee_general, relationship_type, core_document_id_name
                ),
                make_relationship_id(
                    employee_general, relationship_type, target_general
                ),
            }
            if kg_person.company not in implied_entities:
                company_entity = make_entity_id("VENDOR", kg_person.company)

                implied_entities.add(company_entity)
                implied_relationships |= {
                    make_relationship_id(
                        company_entity, relationship_type, core_document_id_name
                    ),
                    make_relationship_id(
                        company_entity, relationship_type, target_general
                    ),
                }

    else:
        account_participant_emails = account_participant_emails | {
            f"{kg_person.name} -- ({kg_person.company})"
        }
        if kg_person.company not in implied_entities:
            account_entity = make_entity_id("ACCOUNT", kg_person.company)
            account_general = make_entity_id("ACCOUNT", "*")
            target_general = list(generalize_entities([core_document_id_name]))[0]

            implied_entities |= {account_entity, account_general}
            implied_relationships |= {
                make_relationship_id(
                    account_entity, relationship_type, core_document_id_name
                ),
                make_relationship_id(
                    account_general, relationship_type, core_document_id_name
                ),
                make_relationship_id(account_entity, relationship_type, target_general),
                make_relationship_id(
                    account_general, relationship_type, target_general
                ),
            }

    return (
        implied_entities,
        implied_relationships,
        company_participant_emails,
        account_participant_emails,
    )


def prepare_llm_content_extraction(
    chunk: KGChunkFormat,
    company_participant_emails: set[str],
    account_participant_emails: set[str],
    kg_config_settings: KGConfigSettings,
) -> str:

    chunk_is_from_call = chunk.source_type.lower() in [
        call_type.value.lower() for call_type in OnyxCallTypes
    ]

    if chunk_is_from_call:

        llm_context = CALL_CHUNK_PREPROCESSING_PROMPT.format(
            participant_string=company_participant_emails,
            account_participant_string=account_participant_emails,
            vendor=kg_config_settings.KG_VENDOR,
            content=chunk.content,
        )
    else:
        llm_context = GENERAL_CHUNK_PREPROCESSING_PROMPT.format(
            content=chunk.content,
            vendor=kg_config_settings.KG_VENDOR,
        )

    return llm_context


def prepare_llm_document_content(
    document_classification_content: KGClassificationContent,
    category_list: str,
    category_definitions: dict[str, dict[str, str | bool]],
    kg_config_settings: KGConfigSettings,
) -> KGDocumentClassificationPrompt:
    """
    Prepare the content for the extraction classification.
    """

    category_definition_string = ""
    for category, category_data in category_definitions.items():
        category_definition_string += f"{category}: {category_data['description']}\n"

    if document_classification_content.source_type.lower() in [
        call_type.value.lower() for call_type in OnyxCallTypes
    ]:
        return _prepare_llm_document_content_call(
            document_classification_content,
            category_list,
            category_definition_string,
            kg_config_settings,
        )

    else:
        return KGDocumentClassificationPrompt(
            llm_prompt=None,
        )


def is_email(email: str) -> bool:
    """
    Check if a string is a valid email address.
    """
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None


def trackinfo_to_str(trackinfo: MetadataTrackInfo | None) -> str:
    """Convert trackinfo to an LLM friendly string"""
    if trackinfo is None:
        return ""

    if trackinfo.type == MetadataTrackType.LIST:
        if trackinfo.values is None:
            return "a list of any suitable values"
        return "a list with possible values: " + ", ".join(trackinfo.values)
    elif trackinfo.type == MetadataTrackType.VALUE:
        if trackinfo.values is None:
            return "any suitable value"
        return "one of: " + ", ".join(trackinfo.values)


def trackinfo_from_str(trackinfo_str: str) -> MetadataTrackInfo | None:
    """Convert back from LLM friendly string to trackinfo"""
    if trackinfo_str == "any suitable value":
        return MetadataTrackInfo(type=MetadataTrackType.VALUE, values=None)
    elif trackinfo_str == "a list of any suitable values":
        return MetadataTrackInfo(type=MetadataTrackType.LIST, values=None)
    elif trackinfo_str.startswith("a list with possible values: "):
        values = set(trackinfo_str[len("a list with possible values: ") :].split(", "))
        return MetadataTrackInfo(type=MetadataTrackType.LIST, values=values)
    elif trackinfo_str.startswith("one of: "):
        values = set(trackinfo_str[len("one of: ") :].split(", "))
        return MetadataTrackInfo(type=MetadataTrackType.VALUE, values=values)
    return None


class EntityTypeMetadataTracker:
    def __init__(self) -> None:
        """
        Tracks the possible values the metadata attributes can take for each entity type.
        """
        self.type_attr_info: dict[str, dict[str, MetadataTrackInfo | None]] = {}

    def import_typeinfo(self) -> None:
        """
        Loads the metadata tracking information from the database.
        """
        with get_session_with_current_tenant() as db_session:
            type_attrs: list[tuple[str, dict[str, dict[str, str]]]] = db_session.query(
                KGEntityType.id_name, KGEntityType.attributes
            ).all()
            self.type_attr_info = {
                entity_type: {
                    attr: trackinfo_from_str(val)
                    for attr, val in attributes["metadata_attributes"].items()
                }
                for entity_type, attributes in type_attrs
                if "metadata_attributes" in attributes
            }

    def export_typeinfo(self) -> None:
        """
        Exports the metadata tracking information to the database.
        """
        with get_session_with_current_tenant() as db_session:
            for entity_type in self.type_attr_info:
                metadata_attributes = {
                    attr: trackinfo_to_str(trackinfo)
                    for attr, trackinfo in self.type_attr_info[entity_type].items()
                }
                db_session.query(KGEntityType).filter(
                    KGEntityType.id_name == entity_type
                ).update(
                    {
                        KGEntityType.attributes: KGEntityType.attributes.op("||")(
                            {"metadata_attributes": metadata_attributes}
                        )
                    },
                    synchronize_session=False,
                )
            db_session.commit()

    def track_metadata(
        self, entity_type: str, attributes: dict[str, str | list[str]]
    ) -> None:
        """
        Tracks which values are possible for the given attributes.
        If the attribute value is a list, we track the values in the list rather than the list itself.
        If we see to many different values, we stop tracking the attribute.
        """
        for attribute, value in attributes.items():
            # ignore types/metadata we are not tracking
            if entity_type not in self.type_attr_info:
                continue
            if attribute not in self.type_attr_info[entity_type]:
                continue

            # determine if the attribute is a list or a value
            trackinfo = self.type_attr_info[entity_type][attribute]
            if trackinfo is None:
                trackinfo = MetadataTrackInfo(
                    type=(
                        MetadataTrackType.VALUE
                        if isinstance(value, str)
                        else MetadataTrackType.LIST
                    ),
                    values=set(),
                )
                self.type_attr_info[entity_type][attribute] = trackinfo

            # if we see to many different values, we stop tracking
            if (
                trackinfo.values is None
                or len(trackinfo.values) > KG_METADATA_TRACKING_THRESHOLD
            ):
                trackinfo.values = None
                continue

            # track the value
            if isinstance(value, str):
                trackinfo.values.add(value)
            else:
                trackinfo.values.update(value)
