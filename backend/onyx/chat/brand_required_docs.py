"""Configurable required document routing for brand knowledge assistants.

The routing layer is intentionally permission-neutral: it may only select from
files already attached to the current persona. Missing config, missing docs, or
non-matching personas all fall back to normal Onyx behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from onyx.db.models import Persona
from onyx.db.models import UserFile
from onyx.file_store.models import FileDescriptor
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type


BRAND_REQUIRED_DOCS_CONFIG_ENV = "ONYX_BRAND_REQUIRED_DOCS_CONFIG_PATH"
DEFAULT_BRAND_REQUIRED_DOCS_CONFIG_PATH = (
    Path(__file__).parent / "brand_required_docs_config" / "novawear.json"
)


def _routing_config_path() -> Path:
    configured_path = os.environ.get(BRAND_REQUIRED_DOCS_CONFIG_ENV)
    if configured_path:
        return Path(configured_path)
    return DEFAULT_BRAND_REQUIRED_DOCS_CONFIG_PATH


def _load_routing_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or _routing_config_path()
    if not path.exists():
        return {}

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return loaded if isinstance(loaded, dict) else {}


def _brand_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    brands = config.get("brands")
    if isinstance(brands, list):
        return [brand for brand in brands if isinstance(brand, dict)]
    if config.get("brand_key") or config.get("persona_name_prefixes"):
        return [config]
    return []


def _persona_name(persona: Persona) -> str:
    return persona.name or ""


def _matches_brand(persona: Persona, brand_config: dict[str, Any]) -> bool:
    if brand_config.get("enabled") is False:
        return False

    persona_name = _persona_name(persona)
    prefixes = brand_config.get("persona_name_prefixes") or []
    if isinstance(prefixes, str):
        prefixes = [prefixes]

    return any(
        isinstance(prefix, str) and persona_name.startswith(prefix)
        for prefix in prefixes
    )


def _brand_config_for_persona(
    persona: Persona, config: dict[str, Any]
) -> dict[str, Any] | None:
    for brand_config in _brand_configs(config):
        if _matches_brand(persona, brand_config):
            return brand_config
    return None


def _persona_role_key(persona: Persona, brand_config: dict[str, Any]) -> str | None:
    persona_name = _persona_name(persona)
    roles = brand_config.get("persona_roles") or []
    if not isinstance(roles, list):
        return None

    for role in roles:
        if not isinstance(role, dict):
            continue
        role_key = role.get("key")
        contains = role.get("name_contains") or []
        if isinstance(contains, str):
            contains = [contains]
        if isinstance(role_key, str) and any(
            isinstance(fragment, str) and fragment in persona_name
            for fragment in contains
        ):
            return role_key

    return None


def _normalize_doc_name(doc_ref: str) -> str:
    return Path(doc_ref).name


def _route_required_doc_names(
    route: dict[str, Any], persona_role_key: str | None
) -> tuple[str, ...]:
    by_persona = route.get("required_docs_by_persona")
    if (
        isinstance(by_persona, dict)
        and persona_role_key
        and persona_role_key in by_persona
    ):
        required_docs = by_persona[persona_role_key]
    else:
        required_docs = route.get("required_docs") or []

    if not isinstance(required_docs, list):
        return ()

    return tuple(
        _normalize_doc_name(doc)
        for doc in required_docs
        if isinstance(doc, str) and doc
    )


def matched_required_doc_names(
    *,
    message: str,
    persona: Persona,
    config: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    routing_config = config if config is not None else _load_routing_config()
    brand_config = _brand_config_for_persona(persona, routing_config)
    if not brand_config:
        return ()

    persona_role_key = _persona_role_key(persona, brand_config)
    if not persona_role_key:
        return ()

    matched: list[str] = []
    routes = brand_config.get("intent_routes") or []
    if not isinstance(routes, list):
        return ()

    normalized_message = message.lower()
    for route in routes:
        if not isinstance(route, dict):
            continue

        allowed_personas = route.get("personas") or []
        if isinstance(allowed_personas, str):
            allowed_personas = [allowed_personas]
        if allowed_personas and persona_role_key not in allowed_personas:
            continue

        triggers = route.get("triggers") or []
        if isinstance(triggers, str):
            triggers = [triggers]
        if any(
            isinstance(trigger, str) and trigger.lower() in normalized_message
            for trigger in triggers
        ):
            matched.extend(_route_required_doc_names(route, persona_role_key))

    return tuple(dict.fromkeys(matched))


def _persona_files_by_basename(persona: Persona) -> dict[str, UserFile]:
    return {Path(user_file.name).name: user_file for user_file in persona.user_files}


def _file_descriptor(user_file: UserFile) -> FileDescriptor:
    return {
        "id": user_file.file_id,
        "type": mime_type_to_chat_file_type(user_file.file_type),
        "name": user_file.name,
        "user_file_id": str(user_file.id),
    }


def brand_required_search_document_ids(
    *,
    message: str,
    persona: Persona,
    config: dict[str, Any] | None = None,
) -> list[str]:
    required_names = matched_required_doc_names(
        message=message, persona=persona, config=config
    )
    if not required_names:
        return []

    persona_files = _persona_files_by_basename(persona)
    return [
        persona_files[name].file_id
        for name in required_names
        if name in persona_files
    ]


def add_brand_required_file_descriptors(
    *,
    message: str,
    persona: Persona,
    file_descriptors: list[FileDescriptor],
    db_session: Session,
    config: dict[str, Any] | None = None,
) -> list[FileDescriptor]:
    """Append configured required docs for the current brand/persona intent.

    The candidate pool is the persona's scoped user files, so this cannot grant
    access to files outside the assistant's configured knowledge scope.
    """
    required_names = matched_required_doc_names(
        message=message, persona=persona, config=config
    )
    if not required_names:
        return file_descriptors

    existing_user_file_ids = {
        str(item.get("user_file_id"))
        for item in file_descriptors
        if item.get("user_file_id")
    }
    persona_files = _persona_files_by_basename(persona)
    routed_files = [
        persona_files[name]
        for name in required_names
        if name in persona_files and str(persona_files[name].id) not in existing_user_file_ids
    ]
    if not routed_files:
        return file_descriptors

    return [*file_descriptors, *[_file_descriptor(user_file) for user_file in routed_files]]
