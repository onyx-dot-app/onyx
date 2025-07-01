import csv
import json
import time
from collections import defaultdict
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import requests
from pydantic import ValidationError
from requests.exceptions import RequestException
from retry import retry

from ee.onyx.server.query_and_chat.models import OneShotQARequest
from ee.onyx.server.query_and_chat.models import OneShotQAResponse
from onyx.chat.models import ThreadMessage
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.constants import MessageType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.regression.search_quality.models import AnalysisSummary
from tests.regression.search_quality.models import CombinedMetrics
from tests.regression.search_quality.models import EvalConfig
from tests.regression.search_quality.models import OneshotQAResult
from tests.regression.search_quality.models import TestQuery
from tests.regression.search_quality.utils import find_document

logger = setup_logger(__name__)

GENERAL_HEADERS = {"Content-Type": "application/json"}
TOP_K_LIST = [1, 3, 5, 10]


class SearchAnswerAnalyzer:
    def __init__(
        self,
        config: EvalConfig,
        tenant_id: str | None = None,
    ):
        if not MULTI_TENANT:
            logger.info("Running in single-tenant mode")
            tenant_id = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
        elif tenant_id is None:
            raise ValueError("Tenant ID is required for multi-tenant")

        self.config = config
        self.tenant_id = tenant_id

        self.results: list[AnalysisSummary] = []
        self.stats: dict[str, list[AnalysisSummary]] = defaultdict(list)
        self.metrics: dict[str, CombinedMetrics] = {}

        # get search related settings
        self._rerank_settings = self._get_rerank_settings()

    def run_analysis(self, dataset_path: Path, export_path: Path) -> None:
        # load and save the dataset
        dataset = self._load_dataset(dataset_path)
        dataset_size = len(dataset)

        # export the processed dataset
        dataset_export_path = export_path / "test_queries.json"
        with dataset_export_path.open("w") as f:
            dataset_serializable = [q.model_dump(mode="json") for q in dataset]
            json.dump(dataset_serializable, f, indent=4)

        # run the analysis
        logger.info("Starting analysis of %d queries...", dataset_size)
        logger.info("Using %d parallel workers", self.config.num_workers)

        indexed_test_cases = [(i, test_case) for i, test_case in enumerate(dataset)]
        indexed_results: dict[int, AnalysisSummary] = {}
        with ThreadPoolExecutor(max_workers=self.config.num_workers) as executor:
            future_to_index = {
                executor.submit(
                    self._run_and_analyze_one_wrapper, test_case_with_index
                ): test_case_with_index[0]
                for test_case_with_index in indexed_test_cases
            }

            # process completed tasks as they finish
            for completed_count, future in enumerate(as_completed(future_to_index), 1):
                try:
                    index, result = future.result()
                    indexed_results[index] = result

                    # update category stats on the fly
                    self.stats["all"].append(result)
                    for cat in result.categories or ["uncategorized"]:
                        self.stats[cat].append(result)
                except Exception as e:
                    print(f"[{completed_count}/{dataset_size}] ✗ Error: {e}")
                    continue

                # print progress with query info
                question = (
                    result.question[:50] + "..."
                    if len(result.question) > 50
                    else result.question
                )
                status = "✓ Found" if result.found else "✗ Not found"
                rank_info = f" (rank {result.rank})" if result.found else ""
                print(
                    f"[{completed_count}/{dataset_size}] {status}{rank_info}: {question}"
                )

        # sort results by original order and build the metrics
        self.results = [indexed_results[i] for i in sorted(indexed_results.keys())]
        self._build_metrics()

    def generate_summary(self) -> None:
        logger.info("Generating summary...")

        metrics_all = self.metrics.get("all")
        if metrics_all is None:
            logger.warning("Nothing to summarize")
            return

        total_queries = metrics_all.total_queries
        found_count = metrics_all.found_count

        print(
            f"Total test queries: {total_queries}\n"
            f"Ground truth found: {found_count} "
            f"({found_count / total_queries * 100:.1f}%)\n"
            f"Ground truth not found: {total_queries - found_count} "
            f"({(total_queries - found_count) / total_queries * 100:.1f}%)"
        )

        if metrics_all.found_count > 0:
            print(
                "\nRank statistics (for found results):\n"
                f"  Average rank: {metrics_all.average_rank:.2f}\n"
                f"  Best rank: {metrics_all.best_rank}\n"
                f"  Worst rank: {metrics_all.worst_rank}\n"
            )
            for k, acc in metrics_all.top_k_accuracy.items():
                print(f"  Top-{k} accuracy: {acc:.1f}%")
            print(f"Average time taken: {metrics_all.average_time_taken:.2f}s")

    def generate_detailed_report(self, export_path: Path) -> None:
        logger.info("Generating detailed report...")

        # persist self.results as json for further inspection
        results_json_path = export_path / "analysis_results.json"
        with results_json_path.open("w") as f:
            json.dump([r.model_dump(mode="json") for r in self.results], f, indent=4)
        logger.info("Saved full analysis results to %s", results_json_path)

        # prepare csv writer
        csv_path = export_path / "results_by_category.csv"
        with csv_path.open("w", newline="") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(
                [
                    "category",
                    "total_queries",
                    "found",
                    "accuracy_pct",
                    "avg_rank_when_found",
                    "avg_time_taken_sec",
                ]
            )

            for category, results in sorted(self.stats.items()):
                if not results:
                    continue

                metrics = self.metrics[category]
                found_count = metrics.found_count
                total_count = metrics.total_queries
                accuracy = found_count / total_count * 100 if total_count > 0 else 0

                print(
                    f"\n{category.upper()}:"
                    f"  total queries: {total_count}\n"
                    f"  found: {found_count} ({accuracy:.1f}%)"
                )
                avg_rank = metrics.average_rank if metrics.found_count > 0 else None
                if avg_rank is not None:
                    print(f"  average rank (when found): {avg_rank:.2f}")
                print(f"  average time taken: {metrics.average_time_taken:.2f}s")

                csv_writer.writerow(
                    [
                        category,
                        total_count,
                        found_count,
                        f"{accuracy:.1f}",
                        f"{avg_rank:.2f}" if avg_rank is not None else "",
                        f"{metrics.average_time_taken:.2f}",
                    ]
                )
        logger.info("Saved category breakdown csv to %s", csv_path)

    def generate_chart(self, export_path: Path) -> None:
        logger.info("Generating search position chart...")

        found_results = [r for r in self.results if r.found]
        not_found_count = len([r for r in self.results if not r.found])

        if not found_results and not_found_count == 0:
            logger.warning("No results to chart")
            return

        # count occurrences at each rank position
        rank_counts: dict[int, int] = defaultdict(int)
        for result in found_results:
            if result.rank is not None:
                rank_counts[result.rank] += 1

        # create the data for plotting
        if found_results:
            max_rank = max(rank_counts.keys())
            positions = list(range(1, max_rank + 1))
            counts = [rank_counts.get(pos, 0) for pos in positions]
        else:
            positions = []
            counts = []

        # add the "not found" bar on the far right
        if not_found_count > 0:
            # add some spacing between found positions and "not found"
            not_found_position = (max(positions) + 2) if positions else 1
            positions.append(not_found_position)
            counts.append(not_found_count)

            # create labels for x-axis
            x_labels = [str(pos) for pos in positions[:-1]] + [
                f"not found\n(>{self.config.max_search_results})"
            ]
        else:
            x_labels = [str(pos) for pos in positions]

        # create the figure and bar chart
        plt.figure(figsize=(14, 6))

        # use different colors for found vs not found
        colors = (
            ["#3498db"] * (len(positions) - 1) + ["#e74c3c"]
            if not_found_count > 0
            else ["#3498db"] * len(positions)
        )
        bars = plt.bar(
            positions, counts, color=colors, alpha=0.7, edgecolor="black", linewidth=0.5
        )

        # customize the chart
        plt.xlabel("Position in Search Results", fontsize=12)
        plt.ylabel("Number of Ground Truth Documents", fontsize=12)
        plt.title(
            "Ground Truth Document Positions in Search Results",
            fontsize=14,
            fontweight="bold",
        )
        plt.grid(axis="y", alpha=0.3)

        # add value labels on top of each bar
        for bar, count in zip(bars, counts):
            if count > 0:
                plt.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.1,
                    str(count),
                    ha="center",
                    va="bottom",
                    fontweight="bold",
                )

        # set x-axis labels
        plt.xticks(positions, x_labels, rotation=45 if not_found_count > 0 else 0)

        # add legend if we have both found and not found
        if not_found_count > 0 and found_results:
            from matplotlib.patches import Patch

            legend_elements = [
                Patch(facecolor="#3498db", alpha=0.7, label="Found in Results"),
                Patch(facecolor="#e74c3c", alpha=0.7, label="Not Found"),
            ]
            plt.legend(handles=legend_elements, loc="upper right")

        # make layout tight and save
        plt.tight_layout()

        chart_file = export_path / "search_position_chart.png"
        plt.savefig(chart_file, dpi=300, bbox_inches="tight")
        logger.info("Search position chart saved to: %s", chart_file)

        plt.show()

    def _load_dataset(self, dataset_path: Path) -> list[TestQuery]:
        """Load the test dataset from a JSON file and validate the ground truth documents."""
        with dataset_path.open("r") as f:
            dataset_raw: list[dict] = json.load(f)

        dataset: list[TestQuery] = []
        for datum in dataset_raw:
            # validate the raw datum
            try:
                test_query = TestQuery(**datum)
            except ValidationError as e:
                logger.error("Incorrectly formatted query: %s", e)
                continue

            # in case the dataset was copied from the previous run export
            if test_query.ground_truth_docids:
                dataset.append(test_query)
                continue

            # validate and get the ground truth documents
            with get_session_with_tenant(tenant_id=self.tenant_id) as db_session:
                for ground_truth in test_query.ground_truth:
                    doc = find_document(ground_truth, db_session)
                    if doc:
                        test_query.ground_truth_docids.append(doc.id)

            if len(test_query.ground_truth_docids) == 0:
                logger.warning(
                    "No ground truth documents found for query: %s, skipping...",
                    test_query.question,
                )
                continue

            dataset.append(test_query)

        return dataset

    @retry(tries=3, delay=1, backoff=2)
    def _perform_oneshot_qa(self, query: str) -> OneshotQAResult:
        """Perform a OneShot QA query against the Onyx API and time it."""
        # create the thread message
        messages = [ThreadMessage(message=query, sender=None, role=MessageType.USER)]

        # create filters (empty to search all sources)
        filters = IndexFilters(
            source_type=None,
            document_set=None,
            time_cutoff=None,
            tags=None,
            access_control_list=None,
        )

        # create the OneShot QA request
        qa_request = OneShotQARequest(
            messages=messages,
            prompt_id=0,  # default prompt
            persona_id=0,  # default persona
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=True,
                filters=filters,
                enable_auto_detect_filters=False,
                limit=self.config.max_search_results,
            ),
            rerank_settings=self._rerank_settings,
            return_contexts=True,
            # TODO: this doesn't quite work, it always generates an answer
            skip_gen_ai_answer_generation=self.config.search_only,
        )

        # send the request
        response = None
        try:
            request_data = qa_request.model_dump()

            start_time = time.monotonic()
            response = requests.post(
                url=f"{self.config.api_url}/query/answer-with-citation",
                json=request_data,
                headers=GENERAL_HEADERS,
                timeout=self.config.request_timeout,
            )
            time_taken = time.monotonic() - start_time
            response.raise_for_status()
            result = OneShotQAResponse.model_validate(response.json())

            # extract documents from the QA response
            if result.docs:
                top_documents = result.docs.top_documents
                return OneshotQAResult(
                    time_taken=time_taken,
                    top_documents=top_documents,
                    answer=result.answer,
                )
            raise RuntimeError(f"OneShot QA returned no documents for query {query}")
        except RequestException as e:
            raise RuntimeError(
                f"OneShot QA failed for query '{query}': {e}."
                f" Response: {response.json()}"
                if response
                else ""
            )

    def _run_and_analyze_one(self, test_case: TestQuery) -> AnalysisSummary:
        result = self._perform_oneshot_qa(test_case.question)

        # compute rank
        rank = self.config.max_search_results
        found = False
        ground_truths = set(test_case.ground_truth_docids)
        for i, doc in enumerate(result.top_documents, 1):
            if doc.document_id in ground_truths:
                rank = i
                found = True
                break

        # TODO: run answer evaluation

        return AnalysisSummary(
            question=test_case.question,
            categories=test_case.categories,
            found=found,
            rank=rank,
            total_results=len(result.top_documents),
            ground_truth_count=len(test_case.ground_truth_docids),
            answer=result.answer,
            time_taken=result.time_taken,
        )

    def _run_and_analyze_one_wrapper(
        self, test_case_with_index: tuple[int, TestQuery]
    ) -> tuple[int, AnalysisSummary]:
        index, test_case = test_case_with_index
        return index, self._run_and_analyze_one(test_case)

    def _compute_combined_metrics(
        self, results: list[AnalysisSummary]
    ) -> CombinedMetrics:
        """Aggregate analysis summaries into CombinedMetrics."""

        total_queries = len(results)
        found_ranks = [r.rank for r in results if r.found and r.rank is not None]
        found_count = len(found_ranks)

        if found_ranks:
            best_rank = min(found_ranks)
            worst_rank = max(found_ranks)
            average_rank = sum(found_ranks) / found_count
        else:
            best_rank = 0
            worst_rank = 0
            average_rank = 0.0

        top_k_accuracy: dict[int, float] = {}
        for k in TOP_K_LIST:
            hits = sum(1 for rank in found_ranks if rank <= k)
            top_k_accuracy[k] = (hits / total_queries * 100) if total_queries else 0.0

        times = [r.time_taken for r in results if r.time_taken is not None]
        avg_time_taken = sum(times) / len(times) if times else 0.0

        return CombinedMetrics(
            total_queries=total_queries,
            found_count=found_count,
            best_rank=best_rank,
            worst_rank=worst_rank,
            average_rank=average_rank,
            top_k_accuracy=top_k_accuracy,
            average_time_taken=avg_time_taken,
        )

    def _build_metrics(self) -> None:
        self.metrics = {
            cat: self._compute_combined_metrics(res_list)
            for cat, res_list in self.stats.items()
        }

    def _get_rerank_settings(self) -> RerankingDetails | None:
        """Fetch the tenant's reranking settings from the database."""
        try:
            with get_session_with_tenant(tenant_id=self.tenant_id) as db_session:
                search_settings = get_current_search_settings(db_session)
                if search_settings:
                    rerank_settings = RerankingDetails.from_db_model(search_settings)
                    if not self.config.rerank_all:
                        return rerank_settings

                    # override the num_rerank to the eval limit
                    rerank_settings = rerank_settings.model_copy(
                        update={"num_rerank": self.config.max_search_results}
                    )
                    return rerank_settings
        except Exception as e:
            logger.warning("Could not load rerank settings from DB: %s", e)
        return None


def run_search_eval(
    dataset_path: Path,
    config: EvalConfig,
    tenant_id: str | None,
) -> None:
    current_dir = Path(__file__).parent

    # create the export folder
    export_folder = current_dir / datetime.now().strftime("eval-%Y-%m-%d-%H-%M-%S")
    export_path = Path(export_folder)
    export_path.mkdir(parents=True, exist_ok=True)
    logger.info("Created export folder: %s", export_path)

    # run the search eval
    analyzer = SearchAnswerAnalyzer(config=config, tenant_id=tenant_id)
    analyzer.run_analysis(dataset_path, export_path)
    analyzer.generate_summary()
    analyzer.generate_detailed_report(export_path)
    analyzer.generate_chart(export_path)


if __name__ == "__main__":
    import argparse

    current_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(description="Run search quality evaluation.")
    parser.add_argument(
        "-d",
        "--dataset",
        type=Path,
        default=current_dir / "test_queries.json",
        help="Path to the test-set JSON file (default: %(default)s).",
    )
    parser.add_argument(
        "-n",
        "--num_search",
        type=int,
        default=50,
        help="Maximum number of search results to check per query (default: %(default)s).",
    )
    parser.add_argument(
        "-a",
        "--num_answer",
        type=int,
        default=25,
        help="Maximum number of search results to use for answer evaluation (default: %(default)s).",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=10,
        help="Number of parallel search requests (default: %(default)s).",
    )
    parser.add_argument(
        "-q",
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "-e",
        "--api_endpoint",
        type=str,
        default="http://127.0.0.1:8080",
        help="Base URL of the Onyx API server (default: %(default)s).",
    )
    parser.add_argument(
        "-s",
        "--search_only",
        action="store_true",
        default=False,
        help="Only perform search and not answer evaluation (default: %(default)s).",
    )
    parser.add_argument(
        "-r",
        "--rerank_all",
        action="store_true",
        default=False,
        help="Always rerank all search results (default: %(default)s).",
    )
    parser.add_argument(
        "-t",
        "--tenant_id",
        type=str,
        default=None,
        help="Tenant ID to use for the evaluation (default: %(default)s).",
    )

    args = parser.parse_args()

    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )

    try:
        run_search_eval(
            args.dataset,
            EvalConfig(
                max_search_results=args.num_search,
                max_answer_context=args.num_answer,
                num_workers=args.workers,
                request_timeout=args.timeout,
                api_url=args.api_endpoint,
                search_only=args.search_only,
                rerank_all=args.rerank_all,
            ),
            args.tenant_id,
        )
    except Exception as e:
        logger.error("Unexpected error during search evaluation: %s", e)
        raise
    finally:
        SqlEngine.reset_engine()
