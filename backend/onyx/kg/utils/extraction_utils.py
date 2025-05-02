import re
from collections import defaultdict
from typing import Dict

from onyx.configs.constants import OnyxCallTypes
from onyx.configs.kg_configs import KG_IGNORE_EMAIL_DOMAINS
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.db.models import Document
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent
from onyx.kg.models import (
    KGDocumentClassificationPrompt,
)
from onyx.kg.models import KGDocumentEntitiesRelationshipsAttributes
from onyx.kg.models import KGEnhancedDocumentMetadata
from onyx.kg.utils.formatting_utils import generalize_entities
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.prompts.kg_prompts import CALL_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import CALL_DOCUMENT_CLASSIFICATION_PROMPT
from onyx.prompts.kg_prompts import GENERAL_CHUNK_PREPROCESSING_PROMPT


def kg_document_entities_relationships_attribute_generation(
    document: Document,
    doc_metadata: KGEnhancedDocumentMetadata,
    active_entities: list[str],
) -> KGDocumentEntitiesRelationshipsAttributes:
    """
    Generate entities, relationships, and attributes for a document.
    """

    document_entity_type = doc_metadata.entity_type
    assert document_entity_type is not None
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
        kg_core_document_id_name = f"{document_entity_type.upper()}:{document_id}"

    # Get implied entities and relationships from primary/secondary owners

    if document_is_from_call:
        owners = (primary_owners or []) + (secondary_owners or [])
        for owner in owners:
            if is_email(owner):
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
                    "participates_in",
                )
            else:
                converted_relationships_to_attributes["participates_in"].append(owner)
    else:
        for owner in primary_owners or []:
            if is_email(owner):
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
                    "leads",
                )
            else:
                converted_relationships_to_attributes["leads"].append(owner)

        for owner in secondary_owners or []:
            if is_email(owner):
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
                    "participates_in",
                )
            else:
                converted_relationships_to_attributes["participates_in"].append(owner)

    if document_attributes is not None:
        cleaned_document_attributes = document_attributes.copy()
        for attribute, value in document_attributes.items():
            if attribute.lower() in [x.lower() for x in active_entities]:
                converted_attributes_to_relationships.add(attribute)
                if isinstance(value, str):
                    implied_entity = f"{attribute.upper()}:{value.capitalize()}"
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        f"{implied_entity}__is_{attribute.lower()}_of__{kg_core_document_id_name}"
                    )

                    implied_entity = f"{attribute.upper()}:*"
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        f"{implied_entity}__is_{attribute.lower()}_of__{kg_core_document_id_name}"
                    )

                    implied_entity = f"{attribute.upper()}:*"
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        f"{implied_entity}__is_{attribute.lower()}_of__{document_entity_type.upper()}:*"
                    )

                    implied_entity = f"{attribute.upper()}:{value.capitalize()}"
                    implied_entities.add(implied_entity)
                    implied_relationships.add(
                        f"{implied_entity}__is_{attribute.lower()}_of__{document_entity_type.upper()}:*"
                    )

                    cleaned_document_attributes.pop(attribute)

                elif isinstance(value, list):
                    for item in value:
                        implied_entity = f"{attribute.upper()}:{item.capitalize()}"
                        implied_entities.add(implied_entity)
                        implied_relationships.add(
                            f"{implied_entity}__is_{attribute.lower()}_of__{kg_core_document_id_name}"
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
) -> KGDocumentClassificationPrompt:
    """
    Calls - prepare prompt for the LLM classification.
    """

    prompt = CALL_DOCUMENT_CLASSIFICATION_PROMPT.format(
        beginning_of_call_content=document_classification_content.classification_content,
        category_list=category_list,
        category_options=category_definition_string,
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
) -> tuple[set[str], set[str], set[str], set[str]]:
    """
    Process a single owner and return updated sets with entities and relationships.

    Returns:
        tuple containing (implied_entities, implied_relationships, company_participant_emails, account_participant_emails)
    """
    assert isinstance(KG_IGNORE_EMAIL_DOMAINS, list)

    kg_person = kg_email_processing(person)
    if any(
        domain.lower() in kg_person.company.lower()
        for domain in KG_IGNORE_EMAIL_DOMAINS
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
            generalized_target_entity = list(
                generalize_entities([core_document_id_name])
            )[0]

            implied_entities = implied_entities | {f"EMPLOYEE:{kg_person.name}"}
            implied_relationships = implied_relationships | {
                f"EMPLOYEE:{kg_person.name}__{relationship_type}__{core_document_id_name}",
                f"EMPLOYEE:{kg_person.name}__{relationship_type}__{generalized_target_entity}",
                f"EMPLOYEE:*__{relationship_type}__{core_document_id_name}",
                f"EMPLOYEE:*__{relationship_type}__{generalized_target_entity}",
            }
            if kg_person.company not in implied_entities:
                implied_entities = implied_entities | {f"VENDOR:{kg_person.company}"}
                implied_relationships = implied_relationships | {
                    f"VENDOR:{kg_person.company}__{relationship_type}__{core_document_id_name}",
                    f"VENDOR:{kg_person.company}__{relationship_type}__{generalized_target_entity}",
                }

    else:
        account_participant_emails = account_participant_emails | {
            f"{kg_person.name} -- ({kg_person.company})"
        }
        if kg_person.company not in implied_entities:
            implied_entities = implied_entities | {
                f"ACCOUNT:{kg_person.company}",
                "ACCOUNT:*",
            }
            implied_relationships = implied_relationships | {
                f"ACCOUNT:{kg_person.company}__{relationship_type}__{core_document_id_name}",
                f"ACCOUNT:*__{relationship_type}__{core_document_id_name}",
            }

            generalized_target_entity = list(
                generalize_entities([core_document_id_name])
            )[0]

            implied_relationships = implied_relationships | {
                f"ACCOUNT:*__{relationship_type}__{generalized_target_entity}",
                f"ACCOUNT:{kg_person.company}__{relationship_type}__{generalized_target_entity}",
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
) -> str:

    chunk_is_from_call = chunk.source_type.lower() in [
        call_type.value.lower() for call_type in OnyxCallTypes
    ]

    if chunk_is_from_call:

        llm_context = CALL_CHUNK_PREPROCESSING_PROMPT.format(
            participant_string=company_participant_emails,
            account_participant_string=account_participant_emails,
            content=chunk.content,
        )
    else:
        llm_context = GENERAL_CHUNK_PREPROCESSING_PROMPT.format(
            content=chunk.content,
        )

    return llm_context


def prepare_llm_document_content(
    document_classification_content: KGClassificationContent,
    category_list: str,
    category_definitions: dict[str, Dict[str, str | bool]],
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
            document_classification_content, category_list, category_definition_string
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
