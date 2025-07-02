from ragas import evaluate  # type: ignore
from ragas import EvaluationDataset  # type: ignore
from ragas import SingleTurnSample  # type: ignore
from ragas.dataset_schema import EvaluationResult  # type: ignore
from ragas.metrics import Faithfulness  # type: ignore
from ragas.metrics import ResponseGroundedness  # type: ignore
from ragas.metrics import ResponseRelevancy  # type: ignore
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.db.models import Document
from onyx.prompts.prompt_utils import build_doc_context_str
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.models import CombinedMetrics
from tests.regression.search_quality.models import GroundTruth
from tests.regression.search_quality.models import RetrievedDocument

logger = setup_logger(__name__)


def find_document(ground_truth: GroundTruth, db_session: Session) -> Document | None:
    """Find a document by its link."""
    # necessary preprocessing of links
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
    return docs[0]


def search_docs_to_doc_contexts(docs: list[SavedSearchDoc]) -> list[RetrievedDocument]:
    return [
        RetrievedDocument(
            document_id=doc.document_id,
            content=build_doc_context_str(
                semantic_identifier=doc.semantic_identifier,
                source_type=doc.source_type,
                content=doc.blurb,  # getting the full content is painful
                metadata_dict=doc.metadata,
                updated_at=doc.updated_at,
                ind=ind,
                include_metadata=True,
            ),
        )
        for ind, doc in enumerate(docs)
    ]


def ragas_evaluate(question: str, answer: str, contexts: list[str]) -> EvaluationResult:
    sample = SingleTurnSample(
        user_input=question,
        retrieved_contexts=contexts,
        response=answer,
    )
    dataset = EvaluationDataset([sample])
    return evaluate(
        dataset,
        metrics=[
            ResponseRelevancy(),
            ResponseGroundedness(),
            Faithfulness(),
        ],
    )


def compute_overall_scores(metrics: CombinedMetrics) -> tuple[float, float]:
    """Compute the overall search and answer quality scores.
    The scores are subjective and may require tuning."""
    # search score
    FOUND_RATIO_WEIGHT = 0.4
    TOP_IMPORTANCE = 0.7  # 0-1, how important is it to be no. 1 over no. 5, etc.

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
    answer_score = (
        metrics.average_response_relevancy
        + metrics.average_response_groundedness
        + metrics.average_faithfulness
    ) / 0.03

    return search_score, answer_score
