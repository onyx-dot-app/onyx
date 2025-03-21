"""
Utility functions for the Backstage connector.
"""

import json
from typing import Dict, Any, List, Optional

from onyx.utils.logger import setup_logger
from .constants import (
    METADATA_KEY,
    KIND_KEY,
    NAME_KEY,
    NAMESPACE_KEY,
    SPEC_KEY,
    RELATIONS_KEY,
    DESCRIPTION_KEY,
)

logger = setup_logger()

def format_entity_text(entity: Dict[str, Any]) -> str:
    """
    Format a Backstage entity into readable text.
    
    Args:
        entity: The entity data from Backstage
        
    Returns:
        Formatted text representation
    """
    kind = entity.get(KIND_KEY, "unknown")
    metadata = entity.get(METADATA_KEY, {})
    name = metadata.get(NAME_KEY, "unnamed")
    namespace = metadata.get(NAMESPACE_KEY, "default")
    spec = entity.get(SPEC_KEY, {})
    relations = entity.get(RELATIONS_KEY, [])
    
    # Format entity data as readable text
    entity_text = f"# {kind.capitalize()}: {name}\n\n"
    
    if DESCRIPTION_KEY in spec:
        entity_text += f"## Description\n{spec[DESCRIPTION_KEY]}\n\n"
    
    entity_text += f"## Metadata\n"
    for key, value in metadata.items():
        if key not in [NAME_KEY, NAMESPACE_KEY]:
            if isinstance(value, (dict, list)):
                entity_text += f"- {key}: {json.dumps(value, indent=2)}\n"
            else:
                entity_text += f"- {key}: {value}\n"
    
    entity_text += f"\n## Specification\n"
    for key, value in spec.items():
        if key != DESCRIPTION_KEY:
            if isinstance(value, (dict, list)):
                entity_text += f"- {key}: {json.dumps(value, indent=2)}\n"
            else:
                entity_text += f"- {key}: {value}\n"
    
    if relations:
        entity_text += f"\n## Relations\n"
        for relation in relations:
            rel_type = relation.get("type", "unknown")
            rel_target = relation.get("targetRef", "unknown")
            entity_text += f"- {rel_type}: {rel_target}\n"
    
    return entity_text

def extract_entity_metadata(entity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract important metadata from a Backstage entity.
    
    Args:
        entity: The entity data from Backstage
        
    Returns:
        Dictionary with relevant metadata fields
    """
    kind = entity.get(KIND_KEY, "unknown")
    metadata = entity.get(METADATA_KEY, {})
    name = metadata.get(NAME_KEY, "unnamed")
    namespace = metadata.get(NAMESPACE_KEY, "default")
    
    result = {
        "kind": kind,
        "name": name,
        "namespace": namespace,
    }
    
    # Include labels if available
    if "labels" in metadata:
        result["labels"] = metadata["labels"]
    
    # Include annotations if available
    if "annotations" in metadata:
        result["annotations"] = metadata["annotations"]
    
    # For components, include type and lifecycle
    if kind == "component" and SPEC_KEY in entity:
        spec = entity[SPEC_KEY]
        if "type" in spec:
            result["component_type"] = spec["type"]
        if "lifecycle" in spec:
            result["lifecycle"] = spec["lifecycle"]
    
    # For APIs, include type and definition
    if kind == "api" and SPEC_KEY in entity:
        spec = entity[SPEC_KEY]
        if "type" in spec:
            result["api_type"] = spec["type"]
    
    return result

def generate_entity_id(entity: Dict[str, Any]) -> str:
    """
    Generate a unique ID for a Backstage entity.
    
    Args:
        entity: The entity data from Backstage
        
    Returns:
        A unique string identifier for the entity
    """
    kind = entity.get(KIND_KEY, "unknown")
    metadata = entity.get(METADATA_KEY, {})
    name = metadata.get(NAME_KEY, "unnamed")
    namespace = metadata.get(NAMESPACE_KEY, "default")
    
    return f"{kind}/{namespace}/{name}"

def get_entity_link(base_url: str, entity: Dict[str, Any]) -> str:
    """
    Get the link to the entity in the Backstage UI.
    
    Args:
        base_url: The base URL of the Backstage instance
        entity: The entity data from Backstage
        
    Returns:
        URL to the entity in the Backstage UI
    """
    kind = entity.get(KIND_KEY, "unknown")
    metadata = entity.get(METADATA_KEY, {})
    name = metadata.get(NAME_KEY, "unnamed")
    namespace = metadata.get(NAMESPACE_KEY, "default")
    
    return f"{base_url}/catalog/{namespace}/{kind}/{name}"