import csv
from collections import defaultdict
from pathlib import Path

from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.context.search.models import RerankingDetails
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_multilingual_expansion
from onyx.document_index.factory import get_default_document_index
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from tests.regression.search_quality.util_config import load_config
from tests.regression.search_quality.util_data import export_test_queries
from tests.regression.search_quality.util_data import load_test_queries
from tests.regression.search_quality.util_eval import evaluate_one_query
from tests.regression.search_quality.util_eval import get_corresponding_document
from tests.regression.search_quality.util_eval import metric_names
from tests.regression.search_quality.util_retrieve import rerank_one_query
from tests.regression.search_quality.util_retrieve import search_one_query

logger = setup_logger(__name__)


def run_search_eval() -> None:
    config = load_config()
    test_queries = load_test_queries()

    # export related
    export_path = Path(config.export_folder)
    export_test_queries(test_queries, export_path / "test_queries.json")
    search_result_path = export_path / "search_results.csv"
    eval_path = export_path / "eval_results.csv"
    aggregate_eval_path = export_path / "aggregate_eval.csv"
    aggregate_results: dict[str, list[list[float]]] = defaultdict(
        lambda: [[] for _ in metric_names]
    )

    with get_session_with_current_tenant() as db_session:
        multilingual_expansion = get_multilingual_expansion(db_session)
        search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(search_settings, None)
        rerank_settings = RerankingDetails.from_db_model(search_settings)

        if config.skip_rerank:
            logger.warning("Reranking is disabled, evaluation will not run")
        elif rerank_settings.rerank_model_name is None:
            raise ValueError(
                "Reranking is enabled but no reranker is configured. "
                "Please set the reranker in the admin panel search settings."
            )

        # run search and evaluate
        logger.info(
            "Running search and evaluation... "
            f"Individual search and evaluation results will be saved to {search_result_path} and {eval_path}"
        )
        with (
            search_result_path.open("w") as search_file,
            eval_path.open("w") as eval_file,
        ):
            search_csv_writer = csv.writer(search_file)
            eval_csv_writer = csv.writer(eval_file)
            search_csv_writer.writerow(
                ["source", "query", "rank", "score", "doc_id", "chunk_id"]
            )
            eval_csv_writer.writerow(["query", *metric_names])

            for query in test_queries:
                # search and write results
                assert query.question_search is not None
                search_chunks = search_one_query(
                    query.question_search,
                    multilingual_expansion,
                    document_index,
                    db_session,
                    config,
                )
                for rank, result in enumerate(search_chunks):
                    search_csv_writer.writerow(
                        [
                            "search",
                            query.question_search,
                            rank,
                            result.score,
                            result.document_id,
                            result.chunk_id,
                        ]
                    )

                rerank_chunks = []
                if not config.skip_rerank:
                    # rerank and write results
                    rerank_chunks = rerank_one_query(
                        query.question, search_chunks, rerank_settings
                    )
                    for rank, result in enumerate(rerank_chunks):
                        search_csv_writer.writerow(
                            [
                                "rerank",
                                query.question,
                                rank,
                                result.score,
                                result.document_id,
                                result.chunk_id,
                            ]
                        )

                # evaluate and write results
                truth_documents = [
                    doc
                    for truth in query.ground_truth
                    if (doc := get_corresponding_document(truth.doc_link, db_session))
                ]
                metrics = evaluate_one_query(
                    search_chunks, rerank_chunks, truth_documents, config.eval_topk
                )
                metric_vals = [getattr(metrics, field) for field in metric_names]
                eval_csv_writer.writerow([query.question, *metric_vals])

                # add to aggregation
                for category in ["all"] + query.categories:
                    for i, val in enumerate(metric_vals):
                        if val is not None:
                            aggregate_results[category][i].append(val)

        # aggregate and write results
        with aggregate_eval_path.open("w") as file:
            aggregate_csv_writer = csv.writer(file)
            aggregate_csv_writer.writerow(["category", *metric_names])

            for category, agg_metrics in aggregate_results.items():
                aggregate_csv_writer.writerow(
                    [
                        category,
                        *(
                            sum(metric) / len(metric) if metric else None
                            for metric in agg_metrics
                        ),
                    ]
                )


if __name__ == "__main__":
    if MULTI_TENANT:
        raise ValueError("Multi-tenant is not supported currently")

    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )

    try:
        run_search_eval()
    except Exception as e:
        logger.error(f"Error running search evaluation: {e}")
        raise e
    finally:
        SqlEngine.reset_engine()
