import re
from typing import Any

from onyx.access.models import ExternalAccess
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def sanitize_string(value: str) -> str:
    """Strip characters that PostgreSQL text/JSONB columns cannot store.

    Removes:
    - NUL bytes (\\x00)
    - UTF-16 surrogates (\\ud800-\\udfff), which are invalid in UTF-8
    """
    sanitized = value.replace("\x00", "")
    sanitized = _SURROGATE_RE.sub("", sanitized)
    if value and not sanitized:
        logger.warning(
            "sanitize_string: all characters were removed from a non-empty string"
        )
    return sanitized


def sanitize_json_like(value: Any) -> Any:
    """Recursively sanitize all strings in a JSON-like structure (dict/list/tuple)."""
    if isinstance(value, str):
        return sanitize_string(value)

    if isinstance(value, list):
        return [sanitize_json_like(item) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_json_like(item) for item in value)

    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, nested_value in value.items():
            cleaned_key = sanitize_string(key) if isinstance(key, str) else key
            sanitized[cleaned_key] = sanitize_json_like(nested_value)
        return sanitized

    return value


def _sanitize_expert_info(expert: BasicExpertInfo) -> BasicExpertInfo:
    return expert.model_copy(
        update={
            "display_name": (
                sanitize_string(expert.display_name)
                if expert.display_name is not None
                else None
            ),
            "first_name": (
                sanitize_string(expert.first_name)
                if expert.first_name is not None
                else None
            ),
            "middle_initial": (
                sanitize_string(expert.middle_initial)
                if expert.middle_initial is not None
                else None
            ),
            "last_name": (
                sanitize_string(expert.last_name)
                if expert.last_name is not None
                else None
            ),
            "email": (
                sanitize_string(expert.email) if expert.email is not None else None
            ),
        }
    )


def _sanitize_external_access(external_access: ExternalAccess) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails={
            sanitize_string(email) for email in external_access.external_user_emails
        },
        external_user_group_ids={
            sanitize_string(group_id)
            for group_id in external_access.external_user_group_ids
        },
        is_public=external_access.is_public,
    )


def sanitize_document_for_postgres(document: Document) -> Document:
    cleaned_doc = document.model_copy(deep=True)

    cleaned_doc.id = sanitize_string(cleaned_doc.id)
    cleaned_doc.semantic_identifier = sanitize_string(cleaned_doc.semantic_identifier)
    if cleaned_doc.title is not None:
        cleaned_doc.title = sanitize_string(cleaned_doc.title)
    if cleaned_doc.parent_hierarchy_raw_node_id is not None:
        cleaned_doc.parent_hierarchy_raw_node_id = sanitize_string(
            cleaned_doc.parent_hierarchy_raw_node_id
        )

    cleaned_doc.metadata = {
        sanitize_string(key): (
            [sanitize_string(item) for item in value]
            if isinstance(value, list)
            else sanitize_string(value)
        )
        for key, value in cleaned_doc.metadata.items()
    }

    if cleaned_doc.doc_metadata is not None:
        cleaned_doc.doc_metadata = sanitize_json_like(cleaned_doc.doc_metadata)

    if cleaned_doc.primary_owners is not None:
        cleaned_doc.primary_owners = [
            _sanitize_expert_info(expert) for expert in cleaned_doc.primary_owners
        ]
    if cleaned_doc.secondary_owners is not None:
        cleaned_doc.secondary_owners = [
            _sanitize_expert_info(expert) for expert in cleaned_doc.secondary_owners
        ]

    if cleaned_doc.external_access is not None:
        cleaned_doc.external_access = _sanitize_external_access(
            cleaned_doc.external_access
        )

    for section in cleaned_doc.sections:
        if section.link is not None:
            section.link = sanitize_string(section.link)
        if section.text is not None:
            section.text = sanitize_string(section.text)
        if section.image_file_id is not None:
            section.image_file_id = sanitize_string(section.image_file_id)

    return cleaned_doc


def sanitize_documents_for_postgres(documents: list[Document]) -> list[Document]:
    return [sanitize_document_for_postgres(document) for document in documents]


def sanitize_hierarchy_node_for_postgres(node: HierarchyNode) -> HierarchyNode:
    cleaned_node = node.model_copy(deep=True)

    cleaned_node.raw_node_id = sanitize_string(cleaned_node.raw_node_id)
    cleaned_node.display_name = sanitize_string(cleaned_node.display_name)
    if cleaned_node.raw_parent_id is not None:
        cleaned_node.raw_parent_id = sanitize_string(cleaned_node.raw_parent_id)
    if cleaned_node.link is not None:
        cleaned_node.link = sanitize_string(cleaned_node.link)

    if cleaned_node.external_access is not None:
        cleaned_node.external_access = _sanitize_external_access(
            cleaned_node.external_access
        )

    return cleaned_node


def sanitize_hierarchy_nodes_for_postgres(
    nodes: list[HierarchyNode],
) -> list[HierarchyNode]:
    return [sanitize_hierarchy_node_for_postgres(node) for node in nodes]
