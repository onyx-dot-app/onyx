import json
import re
from pathlib import Path
from textwrap import indent
from typing import Any
from typing import TextIO

from ragas import evaluate  # type: ignore
from ragas import EvaluationDataset  # type: ignore
from ragas import SingleTurnSample  # type: ignore
from ragas.dataset_schema import EvaluationResult  # type: ignore
from ragas.metrics import FactualCorrectness  # type: ignore
from ragas.metrics import Faithfulness  # type: ignore
from ragas.metrics import ResponseRelevancy  # type: ignore
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SavedSearchDoc
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import Document
from onyx.db.models import FederatedConnector
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.prompts.prompt_utils import build_doc_context_str
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.models import CombinedMetrics
from tests.regression.search_quality.models import GroundTruth
from tests.regression.search_quality.models import RetrievedDocument

logger = setup_logger(__name__)


def get_federated_sources(db_session: Session) -> set[DocumentSource]:
    """Get all federated sources from the database."""
    return {
        source
        for connector in db_session.query(FederatedConnector).all()
        if (source := connector.source.to_non_federated_source()) is not None
    }


def find_document_id(
    ground_truth: GroundTruth,
    federated_sources: set[DocumentSource],
    db_session: Session,
) -> str | None:
    """Find a document by its link and return its id if found."""
    # handle federated sources TODO: maybe make handler dictionary by source if this gets complex
    if ground_truth.doc_source in federated_sources:
        if ground_truth.doc_source == DocumentSource.SLACK:
            groups = re.search(
                r"archives\/([A-Z0-9]+)\/p([0-9]+)", ground_truth.doc_link
            )
            if groups:
                channel_id = groups.group(1)
                message_id = groups.group(2)
                return f"{channel_id}__{message_id[:-6]}.{message_id[-6:]}"

    # preprocess links
    doc_link = ground_truth.doc_link
    if ground_truth.doc_source == DocumentSource.GOOGLE_DRIVE:
        if "/edit" in doc_link:
            doc_link = doc_link.split("/edit", 1)[0]
        elif "/view" in doc_link:
            doc_link = doc_link.split("/view", 1)[0]
    elif ground_truth.doc_source == DocumentSource.FIREFLIES:
        doc_link = doc_link.split("?", 1)[0]

    docs = db_session.query(Document).filter(Document.link.ilike(f"{doc_link}%")).all()
    if len(docs) == 0:
        logger.warning("Could not find ground truth document: %s", doc_link)
        return None
    elif len(docs) > 1:
        logger.warning(
            "Found multiple ground truth documents: %s, using the first one: %s",
            doc_link,
            docs[0].id,
        )
    return docs[0].id


def get_doc_contents(
    docs: list[SavedSearchDoc], tenant_id: str
) -> dict[tuple[str, int], str]:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(search_settings, None)

    filters = IndexFilters(access_control_list=None, tenant_id=tenant_id)

    reqs: list[VespaChunkRequest] = [
        VespaChunkRequest(
            document_id=doc.document_id,
            min_chunk_ind=doc.chunk_ind,
            max_chunk_ind=doc.chunk_ind,
        )
        for doc in docs
    ]

    results = document_index.id_based_retrieval(chunk_requests=reqs, filters=filters)
    return {(doc.document_id, doc.chunk_id): doc.content for doc in results}


def search_docs_to_doc_contexts(
    docs: list[SavedSearchDoc], tenant_id: str
) -> list[RetrievedDocument]:
    try:
        doc_contents = get_doc_contents(docs, tenant_id)
    except Exception as e:
        logger.error("Error getting doc contents: %s", e)
        doc_contents = {}

    return [
        RetrievedDocument(
            document_id=doc.document_id,
            chunk_id=doc.chunk_ind,
            content=build_doc_context_str(
                semantic_identifier=doc.semantic_identifier,
                source_type=doc.source_type,
                content=doc_contents.get(
                    (doc.document_id, doc.chunk_ind), f"Blurb: {doc.blurb}"
                ),
                metadata_dict=doc.metadata,
                updated_at=doc.updated_at,
                ind=ind,
                include_metadata=True,
            ),
        )
        for ind, doc in enumerate(docs)
    ]


def ragas_evaluate(
    question: str, answer: str, contexts: list[str], reference_answer: str | None = None
) -> EvaluationResult:
    sample = SingleTurnSample(
        user_input=question,
        retrieved_contexts=contexts,
        response=answer,
        reference=reference_answer,
    )
    dataset = EvaluationDataset([sample])
    return evaluate(
        dataset,
        metrics=[
            ResponseRelevancy(),
            Faithfulness(),
            *(
                [FactualCorrectness(mode="recall")]
                if reference_answer is not None
                else []
            ),
        ],
    )


def compute_overall_scores(metrics: CombinedMetrics) -> tuple[float, float]:
    """Compute the overall search and answer quality scores.
    The scores are subjective and may require tuning."""
    # search score
    FOUND_RATIO_WEIGHT = 0.4
    TOP_IMPORTANCE = 0.7  # 0-inf, how important is it to be no. 1 over other ranks

    found_ratio = metrics.found_count / metrics.total_queries
    sum_k = sum(1.0 / pow(k, TOP_IMPORTANCE) for k in metrics.top_k_accuracy)
    weighted_topk = sum(
        acc / (pow(k, TOP_IMPORTANCE) * sum_k * 100)
        for k, acc in metrics.top_k_accuracy.items()
    )
    search_score = 100 * (
        FOUND_RATIO_WEIGHT * found_ratio + (1.0 - FOUND_RATIO_WEIGHT) * weighted_topk
    )

    # answer score
    mets = [
        *([metrics.response_relevancy] if metrics.n_response_relevancy > 0 else []),
        *([metrics.faithfulness] if metrics.n_faithfulness > 0 else []),
        *([metrics.factual_correctness] if metrics.n_factual_correctness > 0 else []),
    ]
    answer_score = 100 * sum(mets) / len(mets) if mets else 0.0

    return search_score, answer_score


class LazyJsonWriter:
    def __init__(self, filepath: Path, indent: int = 4) -> None:
        self.filepath = filepath
        self.file: TextIO | None = None
        self.indent = indent

    def append(self, serializable_item: dict[str, Any]) -> None:
        if not self.file:
            self.file = open(self.filepath, "a")
            self.file.write("[\n")
        else:
            self.file.write(",\n")

        data = json.dumps(serializable_item, indent=self.indent)
        self.file.write(indent(data, " " * self.indent))

    def close(self) -> None:
        if not self.file:
            return
        self.file.write("\n]")
        self.file.close()
        self.file = None
