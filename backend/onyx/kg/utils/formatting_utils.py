from collections import defaultdict

from onyx.db.kg_config import KGConfigSettings
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGPerson


def format_entity_id(entity_id_name: str) -> str:
    return make_entity_id(*split_entity_id(entity_id_name))


def make_entity_id(entity_type: str, entity_name: str) -> str:
    return f"{entity_type.upper()}::{entity_name.lower()}"


def split_entity_id(entity_id_name: str) -> list[str]:
    return entity_id_name.split("::")


def get_entity_type(entity_id_name: str) -> str:
    return entity_id_name.split("::", 1)[0].upper()


def format_entity_id_for_models(entity_id_name: str) -> str:
    entity_split = entity_id_name.split("::")
    if len(entity_split) == 2:
        entity_type, entity_name = entity_split
        separator = "::"
    elif len(entity_split) > 2:
        raise ValueError(f"Entity {entity_id_name} is not in the correct format")
    else:
        entity_name = entity_id_name
        separator = entity_type = ""

    formatted_entity_type = entity_type.strip().upper()
    formatted_entity_name = (
        entity_name.strip().replace('"', "").replace("'", "").title()
    )

    return f"{formatted_entity_type}{separator}{formatted_entity_name}"


def format_relationship_id(relationship_id_name: str) -> str:
    return make_relationship_id(*split_relationship_id(relationship_id_name))


def make_relationship_id(
    source_node: str, relationship_type: str, target_node: str
) -> str:
    return (
        f"{format_entity_id(source_node)}__"
        f"{relationship_type.lower()}__"
        f"{format_entity_id(target_node)}"
    )


def split_relationship_id(relationship_id_name: str) -> list[str]:
    return relationship_id_name.split("__")


def format_relationship_type_id(relationship_type_id_name: str) -> str:
    return make_relationship_type_id(
        *split_relationship_type_id(relationship_type_id_name)
    )


def make_relationship_type_id(
    source_node_type: str, relationship_type: str, target_node_type: str
) -> str:
    return (
        f"{source_node_type.upper()}__"
        f"{relationship_type.lower()}__"
        f"{target_node_type.upper()}"
    )


def split_relationship_type_id(relationship_type_id_name: str) -> list[str]:
    return relationship_type_id_name.split("__")


def extract_relationship_type_id(relationship_id_name: str) -> str:
    source_node, relationship_type, target_node = split_relationship_id(
        relationship_id_name
    )
    return make_relationship_type_id(
        get_entity_type(source_node), relationship_type, get_entity_type(target_node)
    )


def aggregate_kg_extractions(
    connector_aggregated_kg_extractions_list: list[KGAggregatedExtractions],
) -> KGAggregatedExtractions:
    aggregated_kg_extractions = KGAggregatedExtractions(
        grounded_entities_document_ids=defaultdict(str),
        entities=defaultdict(int),
        relationships=defaultdict(lambda: defaultdict(int)),
        terms=defaultdict(int),
        attributes=defaultdict(dict),
    )
    for connector_aggregated_kg_extractions in connector_aggregated_kg_extractions_list:
        for (
            grounded_entity,
            document_id,
        ) in connector_aggregated_kg_extractions.grounded_entities_document_ids.items():
            aggregated_kg_extractions.grounded_entities_document_ids[
                grounded_entity
            ] = document_id

        for entity, count in connector_aggregated_kg_extractions.entities.items():
            if entity not in aggregated_kg_extractions.entities:
                aggregated_kg_extractions.entities[entity] = count
            else:
                aggregated_kg_extractions.entities[entity] += count
        for (
            relationship,
            relationship_data,
        ) in connector_aggregated_kg_extractions.relationships.items():
            for source_document_id, count in relationship_data.items():
                if relationship not in aggregated_kg_extractions.relationships:
                    aggregated_kg_extractions.relationships[relationship] = defaultdict(
                        int
                    )
                aggregated_kg_extractions.relationships[relationship][
                    source_document_id
                ] += count
        for term, count in connector_aggregated_kg_extractions.terms.items():
            if term not in aggregated_kg_extractions.terms:
                aggregated_kg_extractions.terms[term] = count
            else:
                aggregated_kg_extractions.terms[term] += count

    return aggregated_kg_extractions


def kg_email_processing(email: str, kg_config_settings: KGConfigSettings) -> KGPerson:
    """
    Process the email.
    """
    name, company_domain = email.split("@")
    assert isinstance(company_domain, str)
    assert isinstance(kg_config_settings.KG_VENDOR_DOMAINS, list)
    assert isinstance(kg_config_settings.KG_VENDOR, str)

    employee = any(
        domain in company_domain for domain in kg_config_settings.KG_VENDOR_DOMAINS
    )
    if employee:
        company = kg_config_settings.KG_VENDOR
    else:
        company = company_domain.capitalize()

    return KGPerson(name=name, company=company, employee=employee)


def generalize_entities(entities: list[str]) -> set[str]:
    """
    Generalize entities to their superclass.
    """
    return {make_entity_id(get_entity_type(entity), "*") for entity in entities}


def generalize_relationships(relationships: list[str]) -> set[str]:
    """
    Generalize relationships to their superclass.
    """
    generalized_relationships: set[str] = set()
    for relationship in relationships:
        assert (
            len(relationship.split("__")) == 3
        ), "Relationship is not in the correct format"
        source_entity, relationship_type, target_entity = split_relationship_id(
            relationship
        )
        source_general = make_entity_id(get_entity_type(source_entity), "*")
        target_general = make_entity_id(get_entity_type(target_entity), "*")
        generalized_relationships |= {
            make_relationship_id(source_general, relationship_type, target_entity),
            make_relationship_id(source_entity, relationship_type, target_general),
            make_relationship_id(source_general, relationship_type, target_general),
        }

    return generalized_relationships
