from onyx.agents.agent_search.kb_search.models import KGSteps

STEP_DESCRIPTIONS: dict[int, KGSteps] = {
    1: KGSteps(
        description="Analyzing the question...",
        activities=[
            "Entities in Query",
            "Relationships in Query",
            "Terms in Query",
            "Time Filters",
        ],
    ),
    2: KGSteps(
        description="Planning the response approach...",
        activities=["Query Execution Strategy", "Answer Format"],
    ),
    3: KGSteps(
        description="Querying the Knowledge Graph...",
        activities=[
            "Knowledge Graph Query",
            "Knowledge Graph Query Results",
            "Query for Source Documents",
            "Source Documents",
        ],
    ),
    4: KGSteps(
        description="Conducting further research on source documents...", activities=[]
    ),
}
