import json

from onyx.configs.constants import OnyxCallTypes
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entity_type import get_entity_types
from onyx.db.kg_config import KGConfigSettings
from onyx.db.models import KGRelationshipType
from onyx.kg.models import (
    KGAttributeTrackInfo,
    KGAttributeTrackType,
    KGChunkFormat,
    KGClassificationInstructions,
    KGClassificationResult,
    KGDocumentDeepExtractionResults,
    KGEnhancedDocumentMetadata,
    KGImpliedExtractionResults,
)
from onyx.kg.utils.formatting_utils import (
    get_entity_type,
    make_relationship_type_id,
)
from onyx.kg.vespa.vespa_interactions import get_document_vespa_contents
from onyx.llm.factory import get_default_llm
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.prompts.kg_prompts import (
    CALL_CHUNK_PREPROCESSING_PROMPT,
    CALL_DOCUMENT_CLASSIFICATION_PROMPT,
    GENERAL_CHUNK_PREPROCESSING_PROMPT,
    MASTER_EXTRACTION_PROMPT,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ensure_trace
from onyx.tracing.framework.traces import TraceContentMode
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()

KG_DOCUMENT_PROCESSING_TRACE_NAME = "kg_document_processing"


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


def kg_deep_extraction(
    document_id: str,
    metadata: KGEnhancedDocumentMetadata,
    implied_extraction: KGImpliedExtractionResults,
    tenant_id: str,
    index_name: str,
    kg_config_settings: KGConfigSettings,
) -> KGDocumentDeepExtractionResults:
    """Perform one document's deep extraction and classification workflow."""
    with ensure_trace(
        KG_DOCUMENT_PROCESSING_TRACE_NAME,
        content_mode=TraceContentMode.METADATA_ONLY,
    ):
        return _kg_deep_extraction(
            document_id=document_id,
            metadata=metadata,
            implied_extraction=implied_extraction,
            tenant_id=tenant_id,
            index_name=index_name,
            kg_config_settings=kg_config_settings,
        )


def _kg_deep_extraction(
    document_id: str,
    metadata: KGEnhancedDocumentMetadata,
    implied_extraction: KGImpliedExtractionResults,
    tenant_id: str,
    index_name: str,
    kg_config_settings: KGConfigSettings,
) -> KGDocumentDeepExtractionResults:
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

    # classify with LLM with Braintrust tracing
    llm = get_default_llm()
    try:
        prompt_msg = UserMessage(content=prompt)
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.KG_DOCUMENT_CLASSIFICATION,
            input_messages=[prompt_msg],
            content_mode=TraceContentMode.METADATA_ONLY,
        ) as span_generation:
            response = llm.invoke(prompt_msg)
            record_llm_response(span_generation, response)
            raw_classification_result = llm_response_to_string(response)

        classification_result = (
            raw_classification_result.replace("```json", "").replace("```", "").strip()
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
        logger.error(
            "Failed to classify document %s. Error: %s", document_entity, str(e)
        )
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

    # extract with LLM with Braintrust tracing
    llm = get_default_llm()
    try:
        prompt_msg = UserMessage(content=prompt)
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.KG_DEEP_EXTRACTION,
            input_messages=[prompt_msg],
            content_mode=TraceContentMode.METADATA_ONLY,
        ) as span_generation:
            response = llm.invoke(prompt_msg)
            record_llm_response(span_generation, response)
            raw_extraction_result = llm_response_to_string(response)

        cleaned_response = (
            raw_extraction_result.replace("{{", "{")
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
            "Failed to process chunks %s from document %s. Error: %s",
            failed_chunks,
            document_entity,
            str(e),
        )
    return None


def trackinfo_to_str(
    trackinfo: KGAttributeTrackInfo | None,
) -> str:
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
