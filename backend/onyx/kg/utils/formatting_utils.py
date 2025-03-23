from collections import defaultdict

from onyx.configs.kg_configs import KG_OWN_COMPANY
from onyx.configs.kg_configs import KG_OWN_EMAIL_DOMAINS
from onyx.kg.models import KGAggregatedExtractions
from onyx.kg.models import KGPerson


def format_entity(entity: str) -> str:
    entity_type, entity_name = entity.split(":")
    return f"{entity_type.upper()}:{entity_name.title()}"


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
        entities=defaultdict(int),
        relationships=defaultdict(int),
        terms=defaultdict(int),
    )

    for connector_aggregated_kg_extractions in connector_aggregated_kg_extractions_list:
        for entity, count in connector_aggregated_kg_extractions.entities.items():
            aggregated_kg_extractions.entities[entity] += count
        for (
            relationship,
            count,
        ) in connector_aggregated_kg_extractions.relationships.items():
            aggregated_kg_extractions.relationships[relationship] += count
        for term, count in connector_aggregated_kg_extractions.terms.items():
            aggregated_kg_extractions.terms[term] += count
    return aggregated_kg_extractions


def kg_email_processing(email: str) -> KGPerson:
    """
    Process the email.
    """
    name, company_domain = email.split("@")

    employee = any(domain in company_domain for domain in KG_OWN_EMAIL_DOMAINS)
    if employee:
        company = KG_OWN_COMPANY
    else:
        company = company_domain.capitalize()

    return KGPerson(name=name, company=company, employee=employee)
