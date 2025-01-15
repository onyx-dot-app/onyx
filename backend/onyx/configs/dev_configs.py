import os

from .chat_configs import NUM_RETURNED_HITS


#####
# Agent Configs
#####

agent_retrieval_stats_os: bool | str | None = os.environ.get(
    "AGENT_RETRIEVAL_STATS", False
)

AGENT_RETRIEVAL_STATS: bool = False
if isinstance(agent_retrieval_stats_os, str) and agent_retrieval_stats_os == "True":
    AGENT_RETRIEVAL_STATS = True
elif isinstance(agent_retrieval_stats_os, bool) and agent_retrieval_stats_os:
    AGENT_RETRIEVAL_STATS = True

agent_max_query_retrieval_results_os: int | str = os.environ.get(
    "AGENT_MAX_QUERY_RETRIEVAL_RESULTS", NUM_RETURNED_HITS
)

AGENT_MAX_QUERY_RETRIEVAL_RESULTS: int = NUM_RETURNED_HITS
try:
    atmqrr = int(agent_max_query_retrieval_results_os)
    AGENT_MAX_QUERY_RETRIEVAL_RESULTS = atmqrr
except ValueError:
    raise ValueError(
        f"MAX_AGENT_QUERY_RETRIEVAL_RESULTS must be an integer, got {AGENT_MAX_QUERY_RETRIEVAL_RESULTS}"
    )


# Reranking agent configs
agent_reranking_stats_os: bool | str | None = os.environ.get(
    "AGENT_RERANKING_TEST", False
)
AGENT_RERANKING_STATS: bool = False
if isinstance(agent_reranking_stats_os, str) and agent_reranking_stats_os == "True":
    AGENT_RERANKING_STATS = True
elif isinstance(agent_reranking_stats_os, bool) and agent_reranking_stats_os:
    AGENT_RERANKING_STATS = True


agent_reranking_max_query_retrieval_results_os: int | str = os.environ.get(
    "AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS", NUM_RETURNED_HITS
)

AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS: int = NUM_RETURNED_HITS

GRAPH_NAME: str = "a"

try:
    atmqrr = int(agent_reranking_max_query_retrieval_results_os)
    AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS = atmqrr
except ValueError:
    raise ValueError(
        f"AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS must be an integer, got {AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS}"
    )