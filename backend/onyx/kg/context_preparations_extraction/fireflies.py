from onyx.configs.kg_configs import KG_IGNORE_EMAIL_DOMAINS
from onyx.configs.kg_configs import KG_OWN_COMPANY
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_kg_entity_by_document
from onyx.kg.context_preparations_extraction.models import ContextPreparation
from onyx.kg.models import KGChunkFormat
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.prompts.kg_prompts import FIREFLIES_PREPROCESSING_PROMPT


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
    implied_entities.add(f"ACCOUNT:{KG_OWN_COMPANY}")
    implied_entities.add(f"{core_document_id_name}")
    implied_relationships.add(
        f"ACCOUNT:{KG_OWN_COMPANY}__participates in__{core_document_id_name}"
    )
    company_participant_emails = set()
    account_participant_emails = set()

    for owner in primary_owners + secondary_owners:
        kg_owner = kg_email_processing(owner)
        if any(domain in kg_owner.company for domain in KG_IGNORE_EMAIL_DOMAINS):
            continue

        if kg_owner.employee:
            company_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
            if kg_owner.name not in implied_entities:
                implied_entities.add(f"EMPLOYEE:{kg_owner.name}")
                implied_relationships.add(
                    f"EMPLOYEE:{kg_owner.name}__participates in__{core_document_id_name}"
                )
                if kg_owner.company not in implied_entities:
                    implied_entities.add(f"ACCOUNT:{kg_owner.company}")
                    implied_relationships.add(
                        f"ACCOUNT:{kg_owner.company}__participates in__{core_document_id_name}"
                    )

        else:
            account_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
            if kg_owner.company not in implied_entities:
                implied_entities.add(f"ACCOUNT:{kg_owner.company}")
                implied_relationships.add(
                    f"ACCOUNT:{kg_owner.company}__participates in__{core_document_id_name}"
                )

    participant_string = "\n  - " + "\n  - ".join(company_participant_emails)
    account_participant_string = "\n  - " + "\n  - ".join(account_participant_emails)

    llm_context = FIREFLIES_PREPROCESSING_PROMPT.format(
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
