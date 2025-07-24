"""
RUN THIS AFTER SEED_DUMMY_DOCS.PY
"""

import random
import time

from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import DOC_EMBEDDING_DIM
from onyx.context.search.models import IndexFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.vespa.index import VespaIndex
from scripts.query_time_check.seed_dummy_docs import TOTAL_ACL_ENTRIES_PER_CATEGORY
from scripts.query_time_check.seed_dummy_docs import TOTAL_DOC_SETS
from shared_configs.model_server_models import Embedding

# make sure these are smaller than TOTAL_ACL_ENTRIES_PER_CATEGORY and TOTAL_DOC_SETS, respectively
NUMBER_OF_ACL_ENTRIES_PER_QUERY = 6
NUMBER_OF_DOC_SETS_PER_QUERY = 2


def get_slowest_99th_percentile(results: list[float]) -> float:
    return sorted(results)[int(0.99 * len(results))]


# Generate random filters
def _random_filters() -> IndexFilters:
    """
    Generate random filters for the query containing:
    - NUMBER_OF_ACL_ENTRIES_PER_QUERY user emails
    - NUMBER_OF_ACL_ENTRIES_PER_QUERY groups
    - NUMBER_OF_ACL_ENTRIES_PER_QUERY external groups
    - NUMBER_OF_DOC_SETS_PER_QUERY document sets
    """
    access_control_list = [
        f"user_email:user_{random.randint(0, TOTAL_ACL_ENTRIES_PER_CATEGORY - 1)}@example.com",
    ]
    acl_indices = random.sample(
        range(TOTAL_ACL_ENTRIES_PER_CATEGORY), NUMBER_OF_ACL_ENTRIES_PER_QUERY
    )
    for i in acl_indices:
        access_control_list.append(f"group:group_{acl_indices[i]}")
        access_control_list.append(f"external_group:external_group_{acl_indices[i]}")

    doc_sets = []
    doc_set_indices = random.sample(
        range(TOTAL_DOC_SETS), NUMBER_OF_ACL_ENTRIES_PER_QUERY
    )
    for i in doc_set_indices:
        doc_sets.append(f"document_set:Document Set {doc_set_indices[i]}")

    return IndexFilters(
        source_type=[DocumentSource.GOOGLE_DRIVE],
        document_set=doc_sets,
        tags=[],
        access_control_list=access_control_list,
    )


def test_hybrid_retrieval_times(
    number_of_queries: int,
) -> None:
    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        multipass_config = get_multipass_config(search_settings)
        index_name = search_settings.index_name

    vespa_index = VespaIndex(
        index_name=index_name,
        secondary_index_name=None,
        large_chunks_enabled=multipass_config.enable_large_chunks,
        secondary_large_chunks_enabled=None,
    )

    # Generate random queries
    queries = [f"Random Query {i}" for i in range(number_of_queries)]

    # Generate random embeddings
    embeddings = [
        Embedding([random.random() for _ in range(DOC_EMBEDDING_DIM)])
        for _ in range(number_of_queries)
    ]

    total_time = 0.0
    results = []
    for i in range(number_of_queries):
        start_time = time.time()

        vespa_index.hybrid_retrieval(
            query=queries[i],
            query_embedding=embeddings[i],
            final_keywords=None,
            filters=_random_filters(),
            hybrid_alpha=0.5,
            time_decay_multiplier=1.0,
            num_to_retrieve=50,
            ranking_profile_type=QueryExpansionType.SEMANTIC,
            offset=0,
            title_content_ratio=0.5,
        )

        end_time = time.time()
        query_time = end_time - start_time
        total_time += query_time
        results.append(query_time)

        print(f"Query {i+1}: {query_time:.4f} seconds")

    avg_time = total_time / number_of_queries
    fast_time = min(results)
    slow_time = max(results)
    ninety_ninth_percentile = get_slowest_99th_percentile(results)
    # Write results to a file
    _OUTPUT_PATH = "query_times_results_large_more.txt"
    with open(_OUTPUT_PATH, "w") as f:
        f.write(f"Average query time: {avg_time:.4f} seconds\n")
        f.write(f"Fastest query: {fast_time:.4f} seconds\n")
        f.write(f"Slowest query: {slow_time:.4f} seconds\n")
        f.write(f"99th percentile: {ninety_ninth_percentile:.4f} seconds\n")
    print(f"Results written to {_OUTPUT_PATH}")

    print(f"\nAverage query time: {avg_time:.4f} seconds")
    print(f"Fastest query: {fast_time:.4f} seconds")
    print(f"Slowest query: {max(results):.4f} seconds")
    print(f"99th percentile: {get_slowest_99th_percentile(results):.4f} seconds")


if __name__ == "__main__":
    test_hybrid_retrieval_times(number_of_queries=1000)
