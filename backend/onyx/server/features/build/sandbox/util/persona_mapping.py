"""Persona mapping utility for demo user identities.

Maps frontend persona selections (work_area + level) to demo user profiles
with name and email for sandbox provisioning.
"""

from typing import TypedDict


class PersonaInfo(TypedDict):
    """Type for persona information."""

    name: str
    email: str


# Mapping from work_area -> level -> persona info
# Note: Frontend uses "product" and "executive", which we map here
PERSONA_MAPPING: dict[str, dict[str, PersonaInfo]] = {
    "engineering": {
        "ic": {
            "name": "Tyler Jenkins",
            "email": "tyler_jenkins@netherite-extraction.onyx.app",
        },
        "manager": {
            "name": "Javier Morales",
            "email": "javier_morales@netherite-extraction.onyx.app",
        },
    },
    "sales": {
        "ic": {
            "name": "Megan Foster",
            "email": "megan_foster@netherite-extraction.onyx.app",
        },
        "manager": {
            "name": "Valeria Cruz",
            "email": "valeria_cruz@netherite-extraction.onyx.app",
        },
    },
    "product": {
        "ic": {
            "name": "Michael Anderson",
            "email": "michael_anderson@netherite-extraction.onyx.app",
        },
        "manager": {
            "name": "David Liu",
            "email": "david_liu@netherite-extraction.onyx.app",
        },
    },
    "marketing": {
        "ic": {
            "name": "Rahul Patel",
            "email": "rahul_patel@netherite-extraction.onyx.app",
        },
        "manager": {
            "name": "Olivia Reed",
            "email": "olivia_reed@netherite-extraction.onyx.app",
        },
    },
    "executive": {
        "manager": {
            "name": "Sarah Mitchell",
            "email": "sarah_mitchell@netherite-extraction.onyx.app",
        },
    },
    "other": {
        "ic": {
            "name": "John Carpenter",
            "email": "john_carpenter@netherite-extraction.onyx.app",
        },
        "manager": {
            "name": "Ralf Schroeder",
            "email": "ralf_schroeder@netherite-extraction.onyx.app",
        },
    },
}


def get_persona_info(work_area: str | None, level: str | None) -> PersonaInfo | None:
    """Get persona info from work area and level.

    Args:
        work_area: User's work area (e.g., "engineering", "product", "sales")
        level: User's level (e.g., "ic", "manager")

    Returns:
        PersonaInfo with name and email, or None if no matching persona
    """
    if not work_area:
        return None

    work_area_lower = work_area.lower().strip()
    level_lower = (level or "manager").lower().strip()

    work_area_mapping = PERSONA_MAPPING.get(work_area_lower)
    if not work_area_mapping:
        return None

    return work_area_mapping.get(level_lower)
