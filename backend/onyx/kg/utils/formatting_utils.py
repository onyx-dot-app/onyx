from collections import defaultdict

from onyx.configs.kg_configs import KG_OWN_COMPANY
from onyx.configs.kg_configs import KG_OWN_EMAIL_DOMAINS
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGPerson


def format_entity(entity: str) -> str:
    if len(entity.split(":")) == 2:
        entity_type, entity_name = entity.split(":")
        return f"{entity_type.upper()}:{entity_name.title()}"
    else:
        return entity


def format_relationship(relationship: str) -> str:
    source_node, relationship_type, target_node = relationship.split("__")
    return (
        f"{format_entity(source_node)}__"
        f"{relationship_type.lower()}__"
        f"{format_entity(target_node)}"
    )


def format_relationship_type(relationship_type: str) -> str:
    source_node_type, relationship_type, target_node_type = relationship_type.split(
        "__"
    )
    return (
        f"{source_node_type.upper()}__"
        f"{relationship_type.lower()}__"
        f"{target_node_type.upper()}"
    )


def generate_relationship_type(relationship: str) -> str:
    source_node, relationship_type, target_node = relationship.split("__")
    return (
        f"{source_node.split(':')[0].upper()}__"
        f"{relationship_type.lower()}__"
        f"{target_node.split(':')[0].upper()}"
    )


def aggregate_kg_extractions(
    connector_aggregated_kg_extractions_list: list[KGAggregatedExtractions],
) -> KGAggregatedExtractions:
    aggregated_kg_extractions = KGAggregatedExtractions(
        grounded_entities_document_ids=defaultdict(str),
        entities=defaultdict(int),
        relationships=defaultdict(lambda: defaultdict(int)),
        terms=defaultdict(int),
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


def kg_email_processing(email: str) -> KGPerson:
    """
    Process the email.
    """
    name, company_domain = email.split("@")

    assert isinstance(KG_OWN_EMAIL_DOMAINS, list)

    employee = any(domain in company_domain for domain in KG_OWN_EMAIL_DOMAINS)
    if employee:
        company = KG_OWN_COMPANY
    else:
        company = company_domain.capitalize()

    return KGPerson(name=name, company=company, employee=employee)


def generalize_entities(entities: list[str]) -> set[str]:
    """
    Generalize entities to their superclass.
    """
    return set([f"{entity.split(':')[0]}:*" for entity in entities])


def generalize_relationships(relationships: list[str]) -> set[str]:
    """
    Generalize relationships to their superclass.
    """
    generalized_relationships: set[str] = set()
    for relationship in relationships:
        assert (
            len(relationship.split("__")) == 3
        ), "Relationship is not in the correct format"
        source_entity, relationship_type, target_entity = relationship.split("__")
        generalized_source_entity = list(generalize_entities([source_entity]))[0]
        generalized_target_entity = list(generalize_entities([target_entity]))[0]
        generalized_relationships.add(
            f"{generalized_source_entity}__{relationship_type}__{target_entity}"
        )
        generalized_relationships.add(
            f"{source_entity}__{relationship_type}__{generalized_target_entity}"
        )
        generalized_relationships.add(
            f"{generalized_source_entity}__{relationship_type}__{generalized_target_entity}"
        )

    return generalized_relationships
