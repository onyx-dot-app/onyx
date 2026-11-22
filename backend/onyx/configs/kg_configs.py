import os

KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX: str = os.environ.get(
    "KG_TEMP_ALLOWED_DOCS_VIEW_NAME_PREFIX", "allowed_docs"
)

KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX: str = os.environ.get(
    "KG_TEMP_KG_RELATIONSHIPS_VIEW_NAME_PREFIX", "kg_relationships_with_access"
)

KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX: str = os.environ.get(
    "KG_TEMP_KG_ENTITIES_VIEW_NAME_PREFIX", "kg_entities_with_access"
)


KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH: int = int(
    os.environ.get("KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH", "2")
)


KG_BETA_ASSISTANT_DESCRIPTION = (
    "The KG Beta assistant uses the Onyx Knowledge Graph (beta) structure \
to answer questions"
)
