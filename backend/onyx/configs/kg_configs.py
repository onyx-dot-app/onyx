import os

KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH: int = int(
    os.environ.get("KG_DEFAULT_MAX_PARENT_RECURSION_DEPTH", "2")
)


KG_BETA_ASSISTANT_DESCRIPTION = (
    "The KG Beta assistant uses the Onyx Knowledge Graph (beta) structure \
to answer questions"
)
