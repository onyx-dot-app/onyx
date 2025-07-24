import json

from langchain_core.messages import HumanMessage

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCallTypes
from onyx.configs.kg_configs import KG_METADATA_TRACKING_THRESHOLD
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.db.entity_type import get_entity_types
from onyx.db.kg_config import KGConfigSettings
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationshipType
from onyx.db.tag import get_structured_tags_for_document
from onyx.kg.models import KGAttributeEntityOption
from onyx.kg.models import KGAttributeTrackInfo
from onyx.kg.models import KGAttributeTrackType
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationInstructions
from onyx.kg.models import KGClassificationResult
from onyx.kg.models import KGDocumentDeepExtractionResults
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.models import KGImpliedExtractionResults
from onyx.kg.models import KGMetadataContent
from onyx.kg.utils.formatting_utils import extract_email
from onyx.kg.utils.formatting_utils import get_entity_type
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.kg.utils.formatting_utils import make_relationship_type_id
from onyx.kg.vespa.vespa_interactions import get_document_vespa_contents
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import message_to_string
from onyx.prompts.kg_prompts import CALL_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import CALL_DOCUMENT_CLASSIFICATION_PROMPT
from onyx.prompts.kg_prompts import GENERAL_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import MASTER_EXTRACTION_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_entity_types_str(active: bool | None = None) -> str:
    """
    Format the entity types into a string for the LLM.
    """
    with get_session_with_current_tenant() as db_session:
        entity_types = get_entity_types(db_session, active)

        entity_types_list: list[str] = []
        for entity_type in entity_types:
            if entity_type.description:
                entity_description = "\n  - Description: " + entity_type.description
            else:
                entity_description = ""

            if entity_type.entity_values:
                allowed_values = "\n  - Allowed Values: " + ", ".join(
                    entity_type.entity_values
                )
            else:
                allowed_values = ""

            attributes = entity_type.parsed_attributes

            entity_type_attribute_list: list[str] = []
            for attribute, values in attributes.attribute_values.items():
                entity_type_attribute_list.append(
                    f"{attribute}: {trackinfo_to_str(values)}"
                )

            if attributes.classification_attributes:
                entity_type_attribute_list.append(
                    # TODO: restructure classification attribute to be a dict of attribute name to classification info
                    # e.g., {scope: {internal: prompt, external: prompt}, sentiment: {positive: prompt, negative: prompt}}
                    "classification: one of: "
                    + ", ".join(attributes.classification_attributes.keys())
                )
            if entity_type_attribute_list:
                entity_attributes = "\n  - Attributes:\n    - " + "\n    - ".join(
                    entity_type_attribute_list
                )
            else:
                entity_attributes = ""

            entity_types_list.append(
                entity_type.id_name
                + entity_description
                + allowed_values
                + entity_attributes
            )

    return "\n".join(entity_types_list)


def get_relationship_types_str(active: bool | None = None) -> str:
    """
    Format the relationship types into a string for the LLM.
    """
    with get_session_with_current_tenant() as db_session:
        active_filters = []
        if active is not None:
            active_filters.append(KGRelationshipType.active == active)

        relationship_types = (
            db_session.query(KGRelationshipType).filter(*active_filters).all()
        )

        relationship_types_list = []
        for rel_type in relationship_types:
            # Format as "source_type__relationship_type__target_type"
            formatted_type = make_relationship_type_id(
                rel_type.source_entity_type_id_name,
                rel_type.type,
                rel_type.target_entity_type_id_name,
            )
            relationship_types_list.append(formatted_type)

    return "\n".join(relationship_types_list)


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


def kg_implied_extraction(
    document: Document,
    doc_metadata: KGEnhancedDocumentMetadata,
    active_entity_types: set[str],
    kg_config_settings: KGConfigSettings,
) -> KGImpliedExtractionResults:
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

    document_is_from_call = document_entity_type.lower() in (
        call_type.value.lower() for call_type in OnyxCallTypes
    )

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

    return KGImpliedExtractionResults(
        document_entity=document_entity_id,
        implied_entities=implied_entities,
        implied_relationships=implied_relationships,
        company_participant_emails=company_participant_emails,
        account_participant_emails=account_participant_emails,
    )


def kg_deep_extraction(
    document_id: str,
    metadata: KGEnhancedDocumentMetadata,
    implied_extraction: KGImpliedExtractionResults,
    tenant_id: str,
    index_name: str,
    kg_config_settings: KGConfigSettings,
) -> KGDocumentDeepExtractionResults:
    """
    Perform deep extraction and classification on the document.
    """
    result = KGDocumentDeepExtractionResults(
        classification_result=None,
        deep_extracted_entities=set(),
        deep_extracted_relationships=set(),
    )

    entity_types_str = get_entity_types_str(active=True)
    relationship_types_str = get_relationship_types_str(active=True)

    for i, chunk_batch in enumerate(
        get_document_vespa_contents(document_id, index_name, tenant_id)
    ):
        # use first batch for classification
        if i == 0 and metadata.classification_enabled:
            if not metadata.classification_instructions:
                raise ValueError(
                    "Classification is enabled but no instructions are provided"
                )
            result.classification_result = kg_classify_document(
                document_entity=implied_extraction.document_entity,
                chunk_batch=chunk_batch,
                implied_extraction=implied_extraction,
                classification_instructions=metadata.classification_instructions,
                kg_config_settings=kg_config_settings,
            )

        # deep extract from this chunk batch
        chunk_batch_results = kg_deep_extract_chunks(
            document_entity=implied_extraction.document_entity,
            chunk_batch=chunk_batch,
            implied_extraction=implied_extraction,
            kg_config_settings=kg_config_settings,
            entity_types_str=entity_types_str,
            relationship_types_str=relationship_types_str,
        )
        if chunk_batch_results is not None:
            result.deep_extracted_entities.update(
                chunk_batch_results.deep_extracted_entities
            )
            result.deep_extracted_relationships.update(
                chunk_batch_results.deep_extracted_relationships
            )

    return result


def kg_classify_document(
    document_entity: str,
    chunk_batch: list[KGChunkFormat],
    implied_extraction: KGImpliedExtractionResults,
    classification_instructions: KGClassificationInstructions,
    kg_config_settings: KGConfigSettings,
) -> KGClassificationResult | None:
    # currently, classification is only done for calls
    # TODO: add support (or use same prompt and format) for non-call documents
    entity_type = get_entity_type(document_entity)
    if entity_type not in (call_type.value for call_type in OnyxCallTypes):
        return None

    # prepare prompt
    implied_extraction.document_entity
    company_participants = implied_extraction.company_participant_emails
    account_participants = implied_extraction.account_participant_emails
    content = (
        f"Title: {chunk_batch[0].title}:\nVendor Participants:\n"
        + "".join(f" - {participant}\n" for participant in company_participants)
        + "Other Participants:\n"
        + "".join(f" - {participant}\n" for participant in account_participants)
        + "Call Content:\n"
        + "\n".join(chunk.content for chunk in chunk_batch)
    )
    category_list = {
        cls: definition.description
        for cls, definition in classification_instructions.classification_class_definitions.items()
    }
    prompt = CALL_DOCUMENT_CLASSIFICATION_PROMPT.format(
        beginning_of_call_content=content,
        category_list=category_list,
        category_options=classification_instructions.classification_options,
        vendor=kg_config_settings.KG_VENDOR,
    )

    # classify with LLM
    primary_llm, _ = get_default_llms()
    msg = [HumanMessage(content=prompt)]
    try:
        raw_classification_result = primary_llm.invoke(msg)
        classification_result = (
            message_to_string(raw_classification_result)
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        # no json parsing here because of reasoning output
        classification_class = classification_result.split("CATEGORY:")[1].strip()

        if (
            classification_class
            in classification_instructions.classification_class_definitions
        ):
            return KGClassificationResult(
                document_entity=document_entity,
                classification_class=classification_class,
            )
    except Exception as e:
        logger.error(f"Failed to classify document {document_entity}. Error: {str(e)}")
    return None


def kg_deep_extract_chunks(
    document_entity: str,
    chunk_batch: list[KGChunkFormat],
    implied_extraction: KGImpliedExtractionResults,
    kg_config_settings: KGConfigSettings,
    entity_types_str: str,
    relationship_types_str: str,
) -> KGDocumentDeepExtractionResults | None:
    # currently, calls are treated differently
    # TODO: either treat some other documents differently too, or ideally all the same way
    entity_type = get_entity_type(document_entity)
    is_call = entity_type in (call_type.value for call_type in OnyxCallTypes)

    content = "\n".join(chunk.content for chunk in chunk_batch)

    # prepare prompt
    if is_call:
        company_participants_str = "".join(
            f" - {participant}\n"
            for participant in implied_extraction.company_participant_emails
        )
        account_participants_str = "".join(
            f" - {participant}\n"
            for participant in implied_extraction.account_participant_emails
        )
        llm_context = CALL_CHUNK_PREPROCESSING_PROMPT.format(
            participant_string=company_participants_str,
            account_participant_string=account_participants_str,
            vendor=kg_config_settings.KG_VENDOR,
            content=content,
        )
    else:
        llm_context = GENERAL_CHUNK_PREPROCESSING_PROMPT.format(
            vendor=kg_config_settings.KG_VENDOR,
            content=content,
        )
    prompt = MASTER_EXTRACTION_PROMPT.format(
        entity_types=entity_types_str,
        relationship_types=relationship_types_str,
    ).replace("---content---", llm_context)

    # extract with LLM
    _, fast_llm = get_default_llms()
    msg = [HumanMessage(content=prompt)]
    try:
        raw_extraction_result = fast_llm.invoke(msg)
        cleaned_response = (
            message_to_string(raw_extraction_result)
            .replace("{{", "{")
            .replace("}}", "}")
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]
        parsed_result = json.loads(cleaned_response)
        return KGDocumentDeepExtractionResults(
            classification_result=None,
            deep_extracted_entities=set(parsed_result.get("entities", [])),
            deep_extracted_relationships={
                rel.replace(" ", "_") for rel in parsed_result.get("relationships", [])
            },
        )
    except Exception as e:
        failed_chunks = [chunk.chunk_id for chunk in chunk_batch]
        logger.error(
            f"Failed to process chunks {failed_chunks} "
            f"from document {document_entity}. Error: {str(e)}"
        )
    return None


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

    person_entity = None
    if kg_person.employee and "EMPLOYEE" in active_entity_types:
        person_entity = make_entity_id("EMPLOYEE", kg_person.name)
    elif not kg_person.employee and "ACCOUNT" in active_entity_types:
        person_entity = make_entity_id("ACCOUNT", kg_person.company)

    if person_entity:
        is_account = person_entity.startswith("ACCOUNT")
        participant_email = f"{kg_person.name} -- ({kg_person.company})"
        return (
            person_entity,
            make_relationship_id(person_entity, relationship_type, document_entity_id),
            participant_email if not is_account else "",
            participant_email if is_account else "",
        )

    return None


def get_batch_documents_metadata(
    document_ids: list[str], connector_source: str
) -> list[KGMetadataContent]:
    """
    Gets the metadata for a batch of documents.
    """
    batch_metadata: list[KGMetadataContent] = []
    source_type = DocumentSource(connector_source).value

    with get_session_with_current_tenant() as db_session:
        for document_id in document_ids:
            # get document metadata
            metadata = get_structured_tags_for_document(document_id, db_session)

            batch_metadata.append(
                KGMetadataContent(
                    document_id=document_id,
                    source_type=source_type,
                    source_metadata=metadata,
                )
            )
    return batch_metadata


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

            # None means marked as don't track
            if trackinfo.values is None:
                continue

            # track the value
            if isinstance(value, str):
                trackinfo.values.add(value)
            else:
                trackinfo.type = KGAttributeTrackType.LIST
                trackinfo.values.update(value)

            # if we see to many different values, we stop tracking
            if len(trackinfo.values) > KG_METADATA_TRACKING_THRESHOLD:
                trackinfo.values = None
