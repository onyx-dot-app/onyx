import re

from onyx.db.kg_config import KGConfigSettings
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
    formatted_entity_name = entity_name.strip().replace('"', "").replace("'", "")

    return f"{formatted_entity_type}{separator}{formatted_entity_name}"


def get_attributes(entity_w_attributes: str) -> dict[str, str]:
    """
    Extract attributes from an entity string.
    E.g., "TYPE::Entity--[attr1: value1, attr2: value2]" -> {"attr1": "value1", "attr2": "value2"}
    """
    attr_split = entity_w_attributes.split("--")
    if len(attr_split) != 2:
        raise ValueError(f"Invalid entity with attributes: {entity_w_attributes}")

    match = re.search(r"\[(.*)\]", attr_split[1])
    if not match:
        return {}

    attr_list_str = match.group(1)
    return {
        attr_split[0].strip(): attr_split[1].strip()
        for attr in attr_list_str.split(",")
        if len(attr_split := attr.split(":", 1)) == 2
    }


def make_entity_w_attributes(entity: str, attributes: dict[str, str]) -> str:
    return f"{entity}--[{', '.join(f'{k}: {v}' for k, v in attributes.items())}]"


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


def extract_email(email: str) -> str | None:
    """
    Extract an email from an arbitrary string (if any).
    Only the first email is returned.
    """
    match = re.search(r"([A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", email)
    return match.group(0) if match else None


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
        # TODO: maybe store a list of domains for each account and use that to match
        # right now, gmail and other random domains are being converted into accounts
        company = company_domain.title()

    return KGPerson(name=name, company=company, employee=employee)
