from onyx.configs.constants import OnyxCallTypes
from onyx.configs.kg_configs import KG_METADATA_TRACKING_THRESHOLD
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.db.kg_config import KGConfigSettings
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.kg.models import KGAttributeEntityOption
from onyx.kg.models import KGAttributeTrackInfo
from onyx.kg.models import KGAttributeTrackType
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent
from onyx.kg.models import (
    KGDocumentClassificationPrompt,
)
from onyx.kg.models import KGDocumentEntitiesRelationshipsAttributes
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.models import KGEntityTypeClassificationInfo
from onyx.kg.utils.formatting_utils import extract_email
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.prompts.kg_prompts import CALL_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import CALL_DOCUMENT_CLASSIFICATION_PROMPT
from onyx.prompts.kg_prompts import GENERAL_CHUNK_PREPROCESSING_PROMPT


def kg_process_owners(
    owner_emails: list[str],
    document_entity_id: str,
    relationship_type: str,
    kg_config_settings: KGConfigSettings,
    active_entity_types: set[str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    owner_entities: set[str] = set()
    owner_relationships: set[str] = set()
    company_participant_emails: set[str] = set()
    account_participant_emails: set[str] = set()

    for owner_email in owner_emails:
        if extract_email(owner_email) is None:
            continue

        process_results = kg_process_person(
            owner_email,
            document_entity_id,
            relationship_type,
            kg_config_settings,
            active_entity_types,
        )
        if process_results is None:
            continue

        (
            owner_entity,
            owner_relationship,
            company_participant_email,
            account_participant_email,
        ) = process_results

        owner_entities.add(owner_entity)
        owner_relationships.add(owner_relationship)
        if company_participant_email:
            company_participant_emails.add(company_participant_email)
        if account_participant_email:
            account_participant_emails.add(account_participant_email)

    return (
        owner_entities,
        owner_relationships,
        company_participant_emails,
        account_participant_emails,
    )


def kg_document_entities_relationships_attribute_generation(
    document: Document,
    doc_metadata: KGEnhancedDocumentMetadata,
    active_entity_types: set[str],
    kg_config_settings: KGConfigSettings,
) -> KGDocumentEntitiesRelationshipsAttributes:
    """
    Generate entities, relationships, and attributes for a document.
    """

    # Get document entity and metadata stuff from the KGEnhancedDocumentMetadata
    document_entity_type = doc_metadata.entity_type
    document_metadata = doc_metadata.document_metadata or {}
    metadata_attribute_conversion = doc_metadata.metadata_attribute_conversion
    if document_entity_type is None or metadata_attribute_conversion is None:
        raise ValueError("Entity type and metadata attributes are required")

    implied_entities: set[str] = set()
    implied_relationships: set[str] = set()

    # Quantity needed for call processing - participants from vendor
    company_participant_emails: set[str] = set()
    # Quantity needed for call processing - external participants
    account_participant_emails: set[str] = set()

    # Chunk treatment variables

    document_is_from_call = document_entity_type.lower() in {
        call_type.value.lower() for call_type in OnyxCallTypes
    }

    # Get core entity

    document_id = document.id
    primary_owners = document.primary_owners
    secondary_owners = document.secondary_owners

    with get_session_with_current_tenant() as db_session:
        document_entity = get_kg_entity_by_document(db_session, document_id)

    if document_entity:
        document_entity_id = document_entity.id_name
    else:
        document_entity_id = make_entity_id(document_entity_type, document_id)

    # Get implied entities and relationships from primary/secondary owners

    if document_is_from_call:
        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
        ) = kg_process_owners(
            owner_emails=(primary_owners or []) + (secondary_owners or []),
            document_entity_id=document_entity_id,
            relationship_type="participates_in",
            kg_config_settings=kg_config_settings,
            active_entity_types=active_entity_types,
        )
    else:
        (
            implied_entities,
            implied_relationships,
            company_participant_emails,
            account_participant_emails,
        ) = kg_process_owners(
            owner_emails=primary_owners or [],
            document_entity_id=document_entity_id,
            relationship_type="leads",
            kg_config_settings=kg_config_settings,
            active_entity_types=active_entity_types,
        )

        (
            participant_entities,
            participant_relationships,
            company_emails,
            account_emails,
        ) = kg_process_owners(
            owner_emails=secondary_owners or [],
            document_entity_id=document_entity_id,
            relationship_type="participates_in",
            kg_config_settings=kg_config_settings,
            active_entity_types=active_entity_types,
        )
        implied_entities.update(participant_entities)
        implied_relationships.update(participant_relationships)
        company_participant_emails.update(company_emails)
        account_participant_emails.update(account_emails)

    # Get implied entities and relationships from document metadata
    for metadata, value in document_metadata.items():
        # get implication property for this metadata
        if metadata not in metadata_attribute_conversion:
            continue
        if (
            implication_property := metadata_attribute_conversion[
                metadata
            ].implication_property
        ) is None:
            continue

        if not isinstance(value, str) and not isinstance(value, list):
            continue
        values: list[str] = [value] if isinstance(value, str) else value

        # create implied entities and relationships
        for item in values:
            if (
                implication_property.implied_entity_type
                == KGAttributeEntityOption.FROM_EMAIL
            ):
                # determine entity type from email
                email = extract_email(item)
                if email is None:
                    continue
                process_results = kg_process_person(
                    email=email,
                    document_entity_id=document_entity_id,
                    relationship_type=implication_property.implied_relationship_name,
                    kg_config_settings=kg_config_settings,
                    active_entity_types=active_entity_types,
                )
                if process_results is None:
                    continue

                (implied_entity, implied_relationship, _, _) = process_results
                implied_entities.add(implied_entity)
                implied_relationships.add(implied_relationship)
            else:
                # use the given entity type
                entity_type = implication_property.implied_entity_type
                if entity_type not in active_entity_types:
                    continue

                implied_entity = make_entity_id(entity_type, item)
                implied_entities.add(implied_entity)
                implied_relationships.add(
                    make_relationship_id(
                        implied_entity,
                        implication_property.implied_relationship_name,
                        document_entity_id,
                    )
                )

    return KGDocumentEntitiesRelationshipsAttributes(
        kg_core_document_id_name=document_entity_id,
        implied_entities=implied_entities,
        implied_relationships=implied_relationships,
        company_participant_emails=company_participant_emails,
        account_participant_emails=account_participant_emails,
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
    email: str,
    document_entity_id: str,
    relationship_type: str,
    kg_config_settings: KGConfigSettings,
    active_entity_types: set[str],
) -> tuple[str, str, str, str] | None:
    """
    Create an employee or account entity from an email address, and a relationship to
    the entity from the document that the email is from.

    Returns:
        tuple containing (person_entity, person_relationship, company_participant_email,
        and account_participant_email), or None if the created entity is not of an
        active entity type or is from an ignored email domain.
    """
    kg_person = kg_email_processing(email, kg_config_settings)
    if any(
        domain.lower() in kg_person.company.lower()
        for domain in kg_config_settings.KG_IGNORE_EMAIL_DOMAINS
    ):
        return None

    if kg_person.employee and "EMPLOYEE" in active_entity_types:
        person_entity = make_entity_id("EMPLOYEE", kg_person.name)
        return (
            person_entity,
            make_relationship_id(person_entity, relationship_type, document_entity_id),
            f"{kg_person.name} -- ({kg_person.company})",
            "",
        )

    elif not kg_person.employee and "ACCOUNT" in active_entity_types:
        person_entity = make_entity_id("ACCOUNT", kg_person.company)
        return (
            person_entity,
            make_relationship_id(person_entity, relationship_type, document_entity_id),
            "",
            f"{kg_person.name} -- ({kg_person.company})",
        )
    return None


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
    category_definitions: dict[str, KGEntityTypeClassificationInfo],
    kg_config_settings: KGConfigSettings,
) -> KGDocumentClassificationPrompt:
    """
    Prepare the content for the extraction classification.
    """

    category_definition_string = ""
    for category, category_data in category_definitions.items():
        category_definition_string += f"{category}: {category_data.description}\n"

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


def trackinfo_to_str(trackinfo: KGAttributeTrackInfo | None) -> str:
    """Convert trackinfo to an LLM friendly string"""
    if trackinfo is None:
        return ""

    if trackinfo.type == KGAttributeTrackType.LIST:
        if trackinfo.values is None:
            return "a list of any suitable values"
        return "a list with possible values: " + ", ".join(trackinfo.values)
    elif trackinfo.type == KGAttributeTrackType.VALUE:
        if trackinfo.values is None:
            return "any suitable value"
        return "one of: " + ", ".join(trackinfo.values)


def trackinfo_to_dict(trackinfo: KGAttributeTrackInfo | None) -> dict | None:
    if trackinfo is None:
        return None
    return {
        "type": trackinfo.type,
        "values": (list(trackinfo.values) if trackinfo.values else None),
    }


class EntityTypeMetadataTracker:
    def __init__(self) -> None:
        """
        Tracks the possible values the metadata attributes can take for each entity type.
        """
        # entity type -> attribute -> trackinfo
        self.entity_attr_info: dict[str, dict[str, KGAttributeTrackInfo | None]] = {}
        self.entity_allowed_attrs: dict[str, set[str]] = {}

    def import_typeinfo(self) -> None:
        """
        Loads the metadata tracking information from the database.
        """
        with get_session_with_current_tenant() as db_session:
            entity_types = db_session.query(KGEntityType).all()

        for entity_type in entity_types:
            self.entity_attr_info[entity_type.id_name] = (
                entity_type.parsed_attributes.attribute_values
            )
            self.entity_allowed_attrs[entity_type.id_name] = {
                attr.name
                for attr in entity_type.parsed_attributes.metadata_attribute_conversion.values()
            }

    def export_typeinfo(self) -> None:
        """
        Exports the metadata tracking information to the database.
        """
        with get_session_with_current_tenant() as db_session:
            for entity_type_id_name, attribute_values in self.entity_attr_info.items():
                db_session.query(KGEntityType).filter(
                    KGEntityType.id_name == entity_type_id_name
                ).update(
                    {
                        KGEntityType.attributes: KGEntityType.attributes.op("||")(
                            {
                                "attribute_values": {
                                    attr: trackinfo_to_dict(info)
                                    for attr, info in attribute_values.items()
                                }
                            }
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
            if entity_type not in self.entity_attr_info:
                continue
            if attribute not in self.entity_allowed_attrs[entity_type]:
                continue

            # determine if the attribute is a list or a value
            trackinfo = self.entity_attr_info[entity_type].get(attribute, None)
            if trackinfo is None:
                trackinfo = KGAttributeTrackInfo(
                    type=(
                        KGAttributeTrackType.VALUE
                        if isinstance(value, str)
                        else KGAttributeTrackType.LIST
                    ),
                    values=set(),
                )
                self.entity_attr_info[entity_type][attribute] = trackinfo

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
