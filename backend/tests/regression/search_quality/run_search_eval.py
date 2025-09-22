import csv
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Event
from threading import Lock
from threading import Semaphore
from typing import cast

import matplotlib.pyplot as plt  # type: ignore
import requests
from dotenv import load_dotenv
from matplotlib.patches import Patch  # type: ignore
from pydantic import ValidationError
from requests.exceptions import RequestException
from retry import retry

# add onyx/backend to path (since this isn't done automatically when running as a script)
current_dir = Path(__file__).parent
onyx_dir = current_dir.parent.parent.parent.parent
sys.path.append(str(onyx_dir / "backend"))

# load env before app_config loads (since env doesn't get loaded when running as a script)
env_path = onyx_dir / ".vscode" / ".env"
if not env_path.exists():
    raise RuntimeError(
        "Could not find .env file. Please create one in the root .vscode directory."
    )
load_dotenv(env_path)

# pylint: disable=E402
# flake8: noqa: E402

from ee.onyx.server.query_and_chat.models import OneShotQARequest
from ee.onyx.server.query_and_chat.models import OneShotQAResponse
from onyx.chat.models import ThreadMessage
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.constants import AuthType
from onyx.configs.constants import MessageType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.regression.search_quality.models import AnalysisSummary
from tests.regression.search_quality.models import CombinedMetrics
from tests.regression.search_quality.models import EvalConfig
from tests.regression.search_quality.models import OneshotQAResult
from tests.regression.search_quality.models import TestQuery
from tests.regression.search_quality.utils import compute_overall_scores
from tests.regression.search_quality.utils import find_document_id
from tests.regression.search_quality.utils import get_federated_sources
from tests.regression.search_quality.utils import LazyJsonWriter
from tests.regression.search_quality.utils import ragas_evaluate
from tests.regression.search_quality.utils import search_docs_to_doc_contexts

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

        # shared analysis results
        self._lock = Lock()
        self._progress_counter = 0
        self._result_writer: LazyJsonWriter | None = None
        self.ranks: list[int | None] = []
        self.metrics: dict[str, CombinedMetrics] = defaultdict(
            lambda: CombinedMetrics(
                total_queries=0,
                found_count=0,
                best_rank=config.max_search_results,
                worst_rank=1,
                average_rank=0.0,
                top_k_accuracy={k: 0.0 for k in TOP_K_LIST},
                response_relevancy=0.0,
                faithfulness=0.0,
                factual_correctness=0.0,
                n_response_relevancy=0,
                n_faithfulness=0,
                n_factual_correctness=0,
                average_time_taken=0.0,
            )
        )

    def run_analysis(self, dataset_path: Path, export_path: Path) -> None:
        # load and save the dataset
        dataset = self._load_dataset(dataset_path)
        dataset_size = len(dataset)
        dataset_export_path = export_path / "test_queries.json"
        with dataset_export_path.open("w") as f:
            dataset_serializable = [q.model_dump(mode="json") for q in dataset]
            json.dump(dataset_serializable, f, indent=4)

        result_export_path = export_path / "search_results.json"
        self._result_writer = LazyJsonWriter(result_export_path)

        # set up rate limiting and threading primitives
        interval = (
            60.0 / self.config.max_request_rate
            if self.config.max_request_rate > 0
            else 0.0
        )
        available_workers = Semaphore(self.config.num_workers)
        stop_event = Event()

        def _submit_wrapper(tc: TestQuery) -> AnalysisSummary:
            try:
                return self._run_and_analyze_one(tc, dataset_size)
            except Exception as e:
                logger.error("Error during analysis: %s", e)
                stop_event.set()
                raise
            finally:
                available_workers.release()

        # run the analysis
        logger.info("Starting analysis of %d queries", dataset_size)
        logger.info("Using %d parallel workers", self.config.num_workers)
        logger.info("Exporting search results to %s", result_export_path)

        with ThreadPoolExecutor(
            max_workers=self.config.num_workers or None
        ) as executor:
            # submit requests at configured rate, break early if any error occurs
            futures = []
            for tc in dataset:
                if stop_event.is_set():
                    break

                available_workers.acquire()
                fut = executor.submit(_submit_wrapper, tc)
                futures.append(fut)

                if (
                    len(futures) != dataset_size
                    and interval > 0
                    and not stop_event.is_set()
                ):
                    time.sleep(interval)

            # ensure all tasks finish and surface any exceptions
            for fut in as_completed(futures):
                fut.result()

        if self._result_writer:
            self._result_writer.close()
        self._aggregate_metrics()

    def generate_detailed_report(self, export_path: Path) -> None:
        logger.info("Generating detailed report...")

        csv_path = export_path / "results_by_category.csv"
        with csv_path.open("w", newline="") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(
                [
                    "category",
                    "total_queries",
                    "found",
                    "percent_found",
                    "best_rank",
                    "worst_rank",
                    "avg_rank",
                    *[f"top_{k}_accuracy" for k in TOP_K_LIST],
                    *(
                        [
                            "avg_response_relevancy",
                            "avg_faithfulness",
                            "avg_factual_correctness",
                        ]
                        if not self.config.search_only
                        else []
                    ),
                    "search_score",
                    *(["answer_score"] if not self.config.search_only else []),
                    "avg_time_taken",
                ]
            )

            for category, metrics in sorted(
                self.metrics.items(), key=lambda c: (0 if c[0] == "all" else 1, c[0])
            ):
                found_count = metrics.found_count
                total_count = metrics.total_queries
                accuracy = found_count / total_count * 100 if total_count > 0 else 0

                print(
                    f"\n{category.upper()}:"
                    f"  total queries: {total_count}\n"
                    f"  found: {found_count} ({accuracy:.1f}%)"
                )
                best_rank = metrics.best_rank if metrics.found_count > 0 else None
                worst_rank = metrics.worst_rank if metrics.found_count > 0 else None
                avg_rank = metrics.average_rank if metrics.found_count > 0 else None
                if metrics.found_count > 0:
                    print(
                        f"  average rank (for found results): {avg_rank:.2f}\n"
                        f"  best rank (for found results): {best_rank:.2f}\n"
                        f"  worst rank (for found results): {worst_rank:.2f}"
                    )
                    for k, acc in metrics.top_k_accuracy.items():
                        print(f"  top-{k} accuracy: {acc:.1f}%")
                if not self.config.search_only:
                    if metrics.n_response_relevancy > 0:
                        print(
                            f"  average response relevancy: {metrics.response_relevancy:.2f}"
                        )
                    if metrics.n_faithfulness > 0:
                        print(f"  average faithfulness: {metrics.faithfulness:.2f}")
                    if metrics.n_factual_correctness > 0:
                        print(
                            f"  average factual correctness: {metrics.factual_correctness:.2f}"
                        )
                search_score, answer_score = compute_overall_scores(metrics)
                print(f"  search score: {search_score:.1f}")
                if not self.config.search_only:
                    print(f"  answer score: {answer_score:.1f}")
                print(f"  average time taken: {metrics.average_time_taken:.2f}s")

                csv_writer.writerow(
                    [
                        category,
                        total_count,
                        found_count,
                        f"{accuracy:.1f}",
                        best_rank or "",
                        worst_rank or "",
                        f"{avg_rank:.2f}" if avg_rank is not None else "",
                        *[f"{acc:.1f}" for acc in metrics.top_k_accuracy.values()],
                        *(
                            [
                                (
                                    f"{metrics.response_relevancy:.2f}"
                                    if metrics.n_response_relevancy > 0
                                    else ""
                                ),
                                (
                                    f"{metrics.faithfulness:.2f}"
                                    if metrics.n_faithfulness > 0
                                    else ""
                                ),
                                (
                                    f"{metrics.factual_correctness:.2f}"
                                    if metrics.n_factual_correctness > 0
                                    else ""
                                ),
                            ]
                            if not self.config.search_only
                            else []
                        ),
                        f"{search_score:.1f}",
                        *(
                            [f"{answer_score:.1f}"]
                            if not self.config.search_only
                            else []
                        ),
                        f"{metrics.average_time_taken:.2f}",
                    ]
                )
        logger.info("Saved category breakdown csv to %s", csv_path)

    def generate_chart(self, export_path: Path) -> None:
        logger.info("Generating search position chart...")

        if len(self.ranks) == 0:
            logger.warning("No results to chart")
            return

        found_count = 0
        not_found_count = 0
        rank_counts: dict[int, int] = defaultdict(int)
        for rank in self.ranks:
            if rank is None:
                not_found_count += 1
            else:
                found_count += 1
                rank_counts[rank] += 1

        # create the data for plotting
        if found_count:
            max_rank = max(rank_counts.keys())
            positions = list(range(1, max_rank + 1))
            counts = [rank_counts.get(pos, 0) for pos in positions]
        else:
            positions = []
            counts = []

        # add the "not found" bar on the far right
        if not_found_count:
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
        if not_found_count and found_count:
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

        with get_session_with_tenant(tenant_id=self.tenant_id) as db_session:
            federated_sources = get_federated_sources(db_session)

        dataset: list[TestQuery] = []
        for datum in dataset_raw:
            # validate the raw datum
            try:
                test_query = TestQuery(**datum)
            except ValidationError as e:
                logger.error("Incorrectly formatted query %s: %s", datum, e)
                continue

            # in case the dataset was copied from the previous run export
            if test_query.ground_truth_docids:
                dataset.append(test_query)
                continue

            # validate and get the ground truth documents
            with get_session_with_tenant(tenant_id=self.tenant_id) as db_session:
                for ground_truth in test_query.ground_truth:
                    if (
                        doc_id := find_document_id(
                            ground_truth, federated_sources, db_session
                        )
                    ) is not None:
                        test_query.ground_truth_docids.append(doc_id)

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
        # create the OneShot QA request
        messages = [ThreadMessage(message=query, sender=None, role=MessageType.USER)]
        filters = IndexFilters(access_control_list=None, tenant_id=self.tenant_id)
        qa_request = OneShotQARequest(
            messages=messages,
            persona_id=0,  # default persona
            retrieval_options=RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=True,
                filters=filters,
                enable_auto_detect_filters=False,
                limit=self.config.max_search_results,
            ),
            skip_gen_ai_answer_generation=self.config.search_only,
        )

        # send the request
        response = None
        try:
            request_data = qa_request.model_dump()
            headers = GENERAL_HEADERS.copy()
            if AUTH_TYPE != AuthType.DISABLED:
                headers["Authorization"] = f"Bearer {os.environ.get('ONYX_API_KEY')}"

            start_time = time.monotonic()
            response = requests.post(
                url=f"{self.config.api_url}/query/answer-with-citation",
                json=request_data,
                headers=headers,
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
        except RequestException as e:
            raise RuntimeError(
                f"OneShot QA failed for query '{query}': {e}."
                f" Response: {response.json()}"
                if response
                else ""
            )
        raise RuntimeError(f"OneShot QA returned no documents for query {query}")

    def _run_and_analyze_one(self, test_case: TestQuery, total: int) -> AnalysisSummary:
        result = self._perform_oneshot_qa(test_case.question)

        # compute rank
        rank = None
        found = False
        ground_truths = set(test_case.ground_truth_docids)
        for i, doc in enumerate(result.top_documents, 1):
            if doc.document_id in ground_truths:
                rank = i
                found = True
                break

        # print search progress and result
        with self._lock:
            self._progress_counter += 1
            completed = self._progress_counter
            status = "✓ Found" if found else "✗ Not found"
            rank_info = f" (rank {rank})" if found else ""
            question_snippet = (
                test_case.question[:50] + "..."
                if len(test_case.question) > 50
                else test_case.question
            )
            print(f"[{completed}/{total}] {status}{rank_info}: {question_snippet}")

        # get the search contents
        retrieved = search_docs_to_doc_contexts(result.top_documents, self.tenant_id)

        # do answer evaluation
        response_relevancy: float | None = None
        faithfulness: float | None = None
        factual_correctness: float | None = None
        contexts = [c.content for c in retrieved[: self.config.max_answer_context]]
        if not self.config.search_only:
            if result.answer is None:
                logger.error(
                    "No answer found for query: %s, skipping answer evaluation",
                    test_case.question,
                )
            else:
                try:
                    ragas_result = ragas_evaluate(
                        question=test_case.question,
                        answer=result.answer,
                        contexts=contexts,
                        reference_answer=test_case.ground_truth_response,
                    ).scores[0]
                    response_relevancy = ragas_result["answer_relevancy"]
                    faithfulness = ragas_result["faithfulness"]
                    factual_correctness = ragas_result.get(
                        "factual_correctness(mode=recall)"
                    )
                except Exception as e:
                    logger.error(
                        "Error evaluating answer for query %s: %s",
                        test_case.question,
                        e,
                    )

        # save results
        analysis = AnalysisSummary(
            question=test_case.question,
            categories=test_case.categories,
            found=found,
            rank=rank,
            total_results=len(result.top_documents),
            ground_truth_count=len(test_case.ground_truth_docids),
            answer=result.answer,
            response_relevancy=response_relevancy,
            faithfulness=faithfulness,
            factual_correctness=factual_correctness,
            retrieved=retrieved,
            time_taken=result.time_taken,
        )
        with self._lock:
            self.ranks.append(analysis.rank)
            if self._result_writer:
                self._result_writer.append(analysis.model_dump(mode="json"))
            self._update_metrics(analysis)

        return analysis

    def _update_metrics(self, result: AnalysisSummary) -> None:
        for cat in result.categories + ["all"]:
            self.metrics[cat].total_queries += 1
            self.metrics[cat].average_time_taken += result.time_taken

            if result.found:
                self.metrics[cat].found_count += 1

                rank = cast(int, result.rank)
                self.metrics[cat].best_rank = min(self.metrics[cat].best_rank, rank)
                self.metrics[cat].worst_rank = max(self.metrics[cat].worst_rank, rank)
                self.metrics[cat].average_rank += rank
                for k in TOP_K_LIST:
                    self.metrics[cat].top_k_accuracy[k] += int(rank <= k)

            if self.config.search_only:
                continue
            if result.response_relevancy is not None:
                self.metrics[cat].response_relevancy += result.response_relevancy
                self.metrics[cat].n_response_relevancy += 1
            if result.faithfulness is not None:
                self.metrics[cat].faithfulness += result.faithfulness
                self.metrics[cat].n_faithfulness += 1
            if result.factual_correctness is not None:
                self.metrics[cat].factual_correctness += result.factual_correctness
                self.metrics[cat].n_factual_correctness += 1

    def _aggregate_metrics(self) -> None:
        for cat in self.metrics:
            total = self.metrics[cat].total_queries
            self.metrics[cat].average_time_taken /= total

            if self.metrics[cat].found_count > 0:
                self.metrics[cat].average_rank /= self.metrics[cat].found_count
            for k in TOP_K_LIST:
                self.metrics[cat].top_k_accuracy[k] /= total
                self.metrics[cat].top_k_accuracy[k] *= 100

            if self.config.search_only:
                continue
            if (n := self.metrics[cat].n_response_relevancy) > 0:
                self.metrics[cat].response_relevancy /= n
            if (n := self.metrics[cat].n_faithfulness) > 0:
                self.metrics[cat].faithfulness /= n
            if (n := self.metrics[cat].n_factual_correctness) > 0:
                self.metrics[cat].factual_correctness /= n


def run_search_eval(
    dataset_path: Path,
    config: EvalConfig,
    tenant_id: str | None,
) -> None:
    # check openai api key is set if doing answer eval (must be called that for ragas to recognize)
    if not config.search_only and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required for answer evaluation. "
            "Please add it to the root .vscode/.env file."
        )

    # check onyx api key is set if auth is enabled
    if AUTH_TYPE != AuthType.DISABLED and not os.environ.get("ONYX_API_KEY"):
        raise RuntimeError(
            "ONYX_API_KEY is required if auth is enabled. "
            "Please create one in the admin panel and add it to the root .vscode/.env file."
        )

    # check onyx is running
    try:
        response = requests.get(
            f"{config.api_url}/health", timeout=config.request_timeout
        )
        response.raise_for_status()
    except RequestException as e:
        raise RuntimeError(f"Could not connect to Onyx API: {e}")

    # create the export folder
    export_folder = current_dir / datetime.now().strftime("eval-%Y-%m-%d-%H-%M-%S")
    export_path = Path(export_folder)
    export_path.mkdir(parents=True, exist_ok=True)
    logger.info("Created export folder: %s", export_path)

    # run the search eval
    analyzer = SearchAnswerAnalyzer(config=config, tenant_id=tenant_id)
    analyzer.run_analysis(dataset_path, export_path)
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
        help="Maximum number of documents to retrieve per search (default: %(default)s).",
    )
    parser.add_argument(
        "-a",
        "--num_answer",
        type=int,
        default=25,
        help="Maximum number of documents to use for answer evaluation (default: %(default)s).",
    )
    parser.add_argument(
        "-w",
        "--max_workers",
        type=int,
        default=10,
        help="Maximum number of concurrent search requests (0 = unlimited, default: %(default)s).",
    )
    parser.add_argument(
        "-r",
        "--max_req_rate",
        type=int,
        default=0,
        help="Maximum number of search requests per minute (0 = unlimited, default: %(default)s).",
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
                num_workers=args.max_workers,
                max_request_rate=args.max_req_rate,
                request_timeout=args.timeout,
                api_url=args.api_endpoint,
                search_only=args.search_only,
            ),
            args.tenant_id,
        )
    except Exception as e:
        logger.error("Unexpected error during search evaluation: %s", e)
        raise
    finally:
        SqlEngine.reset_engine()
