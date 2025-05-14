import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime

import yaml
from sqlalchemy.orm import Session

from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.configs.chat_configs import HYBRID_ALPHA
from onyx.configs.chat_configs import HYBRID_ALPHA_KEYWORD
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.preprocessing.preprocessing import query_analysis
from onyx.context.search.retrieval.search_runner import get_query_embedding
from onyx.context.search.utils import remove_stop_words_and_punctuation
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_multilingual_expansion
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SearchEvalParameters:
    hybrid_alpha: float
    hybrid_alpha_keyword: float
    doc_time_decay: float
    num_returned_hits: int
    rank_profile: QueryExpansionType
    offset: int
    title_content_ratio: float
    user_email: str | None
    export_file: str


def _load_search_parameters() -> SearchEvalParameters:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "search_eval_config.yaml")
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    export_file = config.get("EXPORT_FILE", "search-%Y-%m-%d-%H-%M-%S")
    export_file = datetime.now().strftime(export_file)

    search_parameters = SearchEvalParameters(
        hybrid_alpha=config.get("HYBRID_ALPHA") or HYBRID_ALPHA,
        hybrid_alpha_keyword=config.get("HYBRID_ALPHA_KEYWORD") or HYBRID_ALPHA_KEYWORD,
        doc_time_decay=config.get("DOC_TIME_DECAY") or DOC_TIME_DECAY,
        num_returned_hits=config.get("NUM_RETURNED_HITS") or NUM_RETURNED_HITS,
        rank_profile=config.get("RANK_PROFILE") or QueryExpansionType.SEMANTIC,
        offset=config.get("OFFSET") or 0,
        title_content_ratio=config.get("TITLE_CONTENT_RATIO") or TITLE_CONTENT_RATIO,
        user_email=config.get("USER_EMAIL"),
        export_file=export_file + ".csv",
    )
    logger.info(f"Using search parameters: {search_parameters}")

    logger.info(f"Exporting config to {export_file + '.json'}")
    with open(export_file + ".json", "w") as file:
        search_parameters_dict = search_parameters.__dict__
        search_parameters_dict["rank_profile"] = search_parameters.rank_profile.value
        json.dump(search_parameters_dict, file, indent=4)

    return search_parameters


def _load_queries() -> list[str]:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    queries_path = os.path.join(current_dir, "search_questions.json")
    with open(queries_path, "r") as file:
        return json.load(file)


def _search_one_query(
    query: str,
    multilingual_expansion: list[str],
    document_index: DocumentIndex,
    db_session: Session,
    search_parameters: SearchEvalParameters,
) -> list[InferenceChunkUncleaned]:
    # note that normally query refers to the modified query
    # here, we're sending the original query so the query doesn't randomly change
    query_embedding = get_query_embedding(query, db_session)

    all_query_terms = query.split()
    processed_keywords = (
        remove_stop_words_and_punctuation(all_query_terms)
        if not multilingual_expansion
        else all_query_terms
    )

    is_keyword = query_analysis(query)[0]
    hybrid_alpha = (
        search_parameters.hybrid_alpha_keyword
        if is_keyword
        else search_parameters.hybrid_alpha
    )

    access_control_list = ["PUBLIC"]
    if search_parameters.user_email:
        access_control_list.append(f"user_email:{search_parameters.user_email}")
    filters = IndexFilters(
        tags=[],
        user_file_ids=[],
        user_folder_ids=[],
        access_control_list=access_control_list,
        tenant_id=None,
    )

    return document_index.hybrid_retrieval(
        query=query,
        query_embedding=query_embedding,
        final_keywords=processed_keywords,
        filters=filters,
        hybrid_alpha=hybrid_alpha,
        time_decay_multiplier=search_parameters.doc_time_decay,
        num_to_retrieve=search_parameters.num_returned_hits,
        ranking_profile_type=search_parameters.rank_profile,
        offset=search_parameters.offset,
        title_content_ratio=search_parameters.title_content_ratio,
    )


def run_search_eval() -> None:
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )

    search_parameters = _load_search_parameters()
    queries = _load_queries()

    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(search_settings, None)
        multilingual_expansion = get_multilingual_expansion(db_session)

        with open(search_parameters.export_file, "w") as file:
            csv_writer = csv.writer(file)
            csv_writer.writerow(["query", "rank", "score", "doc_id", "chunk_id"])

            for query in queries:
                results = _search_one_query(
                    query,
                    multilingual_expansion,
                    document_index,
                    db_session,
                    search_parameters,
                )

                for rank, result in enumerate(results):
                    csv_writer.writerow(
                        [query, rank, result.score, result.document_id, result.chunk_id]
                    )

    logger.info(f"Exported results to {search_parameters.export_file}")


if __name__ == "__main__":
    run_search_eval()
