from onyx.configs.kg_configs import KG_IGNORE_EMAIL_DOMAINS
from onyx.configs.kg_configs import KG_OWN_COMPANY
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.kg.context_preparations_extraction.models import ContextPreparation
from onyx.kg.context_preparations_extraction.models import (
    KGDocumentClassificationPrompt,
)
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent
from onyx.kg.utils.formatting_utils import generalize_entities
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.prompts.kg_prompts import FIREFLIES_CHUNK_PREPROCESSING_PROMPT
from onyx.prompts.kg_prompts import FIREFLIES_DOCUMENT_CLASSIFICATION_PROMPT


def prepare_llm_content_fireflies(chunk: KGChunkFormat) -> ContextPreparation:
    """
    Fireflies - prepare the content for the LLM.
    """

    document_id = chunk.document_id
    primary_owners = chunk.primary_owners
    secondary_owners = chunk.secondary_owners
    content = chunk.content
    chunk.title.capitalize()

    implied_entities = set()
    implied_relationships = set()

    with get_session_with_current_tenant() as db_session:
        core_document = get_kg_entity_by_document(db_session, document_id)

    if core_document:
        core_document_id_name = core_document.id_name
    else:
        core_document_id_name = f"FIREFLIES:{document_id}"

    # Do we need this here?
    implied_entities.add(f"VENDOR:{KG_OWN_COMPANY}")
    implied_entities.add(f"{core_document_id_name}")
    implied_entities.add("FIREFLIES:*")
    implied_relationships.add(
        f"VENDOR:{KG_OWN_COMPANY}__participates_in__{core_document_id_name}"
    )
    company_participant_emails = set()
    account_participant_emails = set()

    for owner in primary_owners + secondary_owners:
        assert isinstance(KG_IGNORE_EMAIL_DOMAINS, list)

        kg_owner = kg_email_processing(owner)
        if any(
            domain.lower() in kg_owner.company.lower()
            for domain in KG_IGNORE_EMAIL_DOMAINS
        ):
            continue

        if kg_owner.employee:
            company_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
            if kg_owner.name not in implied_entities:
                generalized_target_entity = list(
                    generalize_entities([core_document_id_name])
                )[0]

                implied_entities.add(f"EMPLOYEE:{kg_owner.name}")
                implied_relationships.add(
                    f"EMPLOYEE:{kg_owner.name}__participates_in__{core_document_id_name}"
                )
                implied_relationships.add(
                    f"EMPLOYEE:{kg_owner.name}__participates_in__{generalized_target_entity}"
                )
                implied_relationships.add(
                    f"EMPLOYEE:*__participates_in__{core_document_id_name}"
                )
                implied_relationships.add(
                    f"EMPLOYEE:*__participates_in__{generalized_target_entity}"
                )
                if kg_owner.company not in implied_entities:
                    implied_entities.add(f"VENDOR:{kg_owner.company}")
                    implied_relationships.add(
                        f"VENDOR:{kg_owner.company}__participates_in__{core_document_id_name}"
                    )
                    implied_relationships.add(
                        f"VENDOR:{kg_owner.company}__participates_in__{generalized_target_entity}"
                    )

        else:
            account_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
            if kg_owner.company not in implied_entities:
                implied_entities.add(f"ACCOUNT:{kg_owner.company}")
                implied_entities.add("ACCOUNT:*")
                implied_relationships.add(
                    f"ACCOUNT:{kg_owner.company}__participates_in__{core_document_id_name}"
                )
                implied_relationships.add(
                    f"ACCOUNT:*__participates_in__{core_document_id_name}"
                )

                generalized_target_entity = list(
                    generalize_entities([core_document_id_name])
                )[0]

                implied_relationships.add(
                    f"ACCOUNT:*__participates_in__{generalized_target_entity}"
                )
                implied_relationships.add(
                    f"ACCOUNT:{kg_owner.company}__participates_in__{generalized_target_entity}"
                )

    participant_string = "\n  - " + "\n  - ".join(company_participant_emails)
    account_participant_string = "\n  - " + "\n  - ".join(account_participant_emails)

    llm_context = FIREFLIES_CHUNK_PREPROCESSING_PROMPT.format(
        participant_string=participant_string,
        account_participant_string=account_participant_string,
        content=content,
    )

    return ContextPreparation(
        llm_context=llm_context,
        core_entity=core_document_id_name,
        implied_entities=list(implied_entities),
        implied_relationships=list(implied_relationships),
        implied_terms=[],
    )


def prepare_llm_document_content_fireflies(
    document_classification_content: KGClassificationContent,
    category_list: str,
    category_definition_string: str,
) -> KGDocumentClassificationPrompt:
    """
    Fireflies - prepare prompt for the LLM classification.
    """

    prompt = FIREFLIES_DOCUMENT_CLASSIFICATION_PROMPT.format(
        beginning_of_call_content=document_classification_content.classification_content,
        category_list=category_list,
        category_options=category_definition_string,
    )

    return KGDocumentClassificationPrompt(
        llm_prompt=prompt,
    )


def get_classification_content_from_fireflies_chunks(
    first_num_classification_chunks: list[dict],
) -> str:
    """
    Creates a KGClassificationContent object from a list of Fireflies chunks.
    """

    assert isinstance(KG_IGNORE_EMAIL_DOMAINS, list)

    primary_owners = first_num_classification_chunks[0]["fields"]["primary_owners"]
    secondary_owners = first_num_classification_chunks[0]["fields"]["secondary_owners"]

    company_participant_emails = set()
    account_participant_emails = set()

    for owner in primary_owners + secondary_owners:
        kg_owner = kg_email_processing(owner)
        if any(
            domain.lower() in kg_owner.company.lower()
            for domain in KG_IGNORE_EMAIL_DOMAINS
        ):
            continue

        if kg_owner.employee:
            company_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
        else:
            account_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")

    participant_string = "\n  - " + "\n  - ".join(company_participant_emails)
    account_participant_string = "\n  - " + "\n  - ".join(account_participant_emails)

    title_string = first_num_classification_chunks[0]["fields"]["title"]
    content_string = "\n".join(
        [
            chunk_content["fields"]["content"]
            for chunk_content in first_num_classification_chunks
        ]
    )

    classification_content = f"{title_string}\n\nVendor Participants:\n{participant_string}\n\n\
Other Participants:\n{account_participant_string}\n\nBeginning of Call:\n{content_string}"

    return classification_content
