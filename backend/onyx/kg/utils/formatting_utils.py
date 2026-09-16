import re


def get_entity_type(entity_id_name: str) -> str:
    return entity_id_name.split("::", 1)[0].upper()


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


def make_relationship_type_id(
    source_node_type: str, relationship_type: str, target_node_type: str
) -> str:
    return f"{source_node_type.upper()}__{relationship_type.lower()}__{target_node_type.upper()}"
