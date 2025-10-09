"""
Evaluation script for testing retrieval accuracy on the ACCURACY_TESTING collection.

Loads questions from target_questions.jsonl, performs searches using Cohere embeddings,
and evaluates if the correct documents are retrieved.

Metrics:
- Top-1 accuracy: Correct document is in position 1
- Top-5 accuracy: Correct document is in top 5
- Top-10 accuracy: Correct document is in top 10
- MRR (Mean Reciprocal Rank): Average of 1/rank for correct documents
"""

import json
import os
import time
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cohere
from dotenv import load_dotenv
from fastembed import SparseTextEmbedding
from qdrant_client.models import Filter
from qdrant_client.models import Fusion
from qdrant_client.models import FusionQuery
from qdrant_client.models import Prefetch
from qdrant_client.models import SparseVector

from scratch.qdrant.accuracy_testing.target_document_schema import TargetQuestion
from scratch.qdrant.client import QdrantClient
from scratch.qdrant.schemas.collection_name import CollectionName


def load_questions(jsonl_path: Path) -> list[TargetQuestion]:
    """Load questions from JSONL file."""
    questions = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                questions.append(TargetQuestion(**data))
    return questions


def embed_query_with_cohere(
    query: str,
    cohere_client: cohere.Client,
    model: str = "embed-english-v3.0",
) -> list[float]:
    """Embed a single query using Cohere."""
    response = cohere_client.embed(
        texts=[query],
        model=model,
        input_type="search_query",  # Use search_query for queries
    )
    return response.embeddings[0]


def embed_query_with_bm25(
    query: str,
    sparse_embedding_model: SparseTextEmbedding,
) -> SparseVector:
    """Embed a single query using BM25."""
    sparse_embedding = next(sparse_embedding_model.query_embed(query))
    return SparseVector(
        indices=sparse_embedding.indices.tolist(),
        values=sparse_embedding.values.tolist(),
    )


def hybrid_search_qdrant(
    dense_query_vector: list[float],
    sparse_query_vector: SparseVector,
    qdrant_client: QdrantClient,
    collection_name: CollectionName,
    limit: int = 10,
    prefetch_limit: int | None = None,
    query_filter: Filter | None = None,
):
    """Perform hybrid search using both dense and sparse vectors."""
    # If prefetch_limit not specified, use limit * 2
    effective_prefetch_limit = (
        prefetch_limit if prefetch_limit is not None else limit * 2
    )

    return qdrant_client.query_points(
        collection_name=collection_name,
        prefetch=[
            Prefetch(
                query=sparse_query_vector,
                using="sparse",
                limit=effective_prefetch_limit,
                filter=query_filter,
            ),
            Prefetch(
                query=dense_query_vector,
                using="dense",
                limit=effective_prefetch_limit,
                filter=query_filter,
            ),
        ],
        fusion_query=FusionQuery(fusion=Fusion.DBSF),
        with_payload=True,
        limit=limit,
    )


def extract_ground_truth_doc_ids(question: TargetQuestion) -> set[str]:
    """
    Extract ground truth document IDs from question metadata.

    For file-based sources: uses the 'source' field
        Example: "company_policies/Succession-planning-policy.docx"

    For Slack messages: uses the 'thread_ts' field
        Example: "1706889457.275089"
    """
    doc_ids = set()
    for doc_source in question.metadata.doc_source:
        if doc_source.source:
            # File-based source
            doc_ids.add(doc_source.source)
        elif doc_source.thread_ts:
            # Slack message - use thread_ts as document_id
            doc_ids.add(doc_source.thread_ts)
    return doc_ids


def evaluate_search_results(
    search_results,
    ground_truth_doc_ids: set[str],
) -> dict:
    """
    Evaluate search results against ground truth with deduplication.

    For multi-document ground truth, deduplicates retrieved docs to get unique
    documents before checking recall.

    Example:
        Ground truth: {A, B}
        Retrieved: [A, A, A, B, C] -> Deduplicated: [A, B, C]
        Recall@3: 2/2 = 1.0 (100%)

    Returns:
        Dict with recall metrics at different k values
    """
    retrieved_doc_ids = [
        point.payload.get("document_id") for point in search_results.points
    ]

    # Deduplicate while preserving order
    seen = set()
    deduplicated_doc_ids = []
    for doc_id in retrieved_doc_ids:
        if doc_id not in seen:
            seen.add(doc_id)
            deduplicated_doc_ids.append(doc_id)

    # Find rank of first correct document (for MRR)
    first_correct_rank = None
    for rank, doc_id in enumerate(deduplicated_doc_ids, start=1):
        if doc_id in ground_truth_doc_ids:
            first_correct_rank = rank
            break

    # Calculate recall at different k values (using deduplicated results)
    def recall_at_k(k: int) -> float:
        """Calculate recall@k: fraction of ground truth docs found in top k"""
        top_k_docs = set(deduplicated_doc_ids[:k])
        found_docs = top_k_docs & ground_truth_doc_ids
        return (
            len(found_docs) / len(ground_truth_doc_ids) if ground_truth_doc_ids else 0.0
        )

    # Calculate recall at multiple k values
    recall_metrics = {
        "recall_at_1": recall_at_k(1),
        "recall_at_3": recall_at_k(3),
        "recall_at_5": recall_at_k(5),
        "recall_at_10": recall_at_k(10),
        "recall_at_25": recall_at_k(25),
        "recall_at_50": recall_at_k(50),
    }

    # Perfect recall (all ground truth docs found) at different k
    return {
        "top_1_hit": recall_metrics["recall_at_1"] == 1.0,
        "top_3_hit": recall_metrics["recall_at_3"] == 1.0,
        "top_5_hit": recall_metrics["recall_at_5"] == 1.0,
        "top_10_hit": recall_metrics["recall_at_10"] == 1.0,
        **recall_metrics,
        "reciprocal_rank": 1.0 / first_correct_rank if first_correct_rank else 0.0,
        "first_correct_rank": first_correct_rank,
        "num_ground_truth": len(ground_truth_doc_ids),
        "retrieved_doc_ids": retrieved_doc_ids[:50],  # Keep first 50 (with duplicates)
        "deduplicated_doc_ids": deduplicated_doc_ids[:50],  # Keep deduplicated top 50
    }


def evaluate_single_question(
    question: TargetQuestion,
    cohere_client: cohere.Client,
    sparse_embedding_model: SparseTextEmbedding,
    qdrant_client: QdrantClient,
    collection_name: CollectionName,
    cohere_model: str,
) -> dict:
    """Evaluate a single question using hybrid search. This will be run in parallel."""
    # Embed query with Cohere (dense)
    dense_query_vector = embed_query_with_cohere(
        question.question, cohere_client, cohere_model
    )

    # Embed query with BM25 (sparse)
    sparse_query_vector = embed_query_with_bm25(
        question.question, sparse_embedding_model
    )

    # Hybrid search (retrieve 50 to calculate recall@25 and recall@50)
    search_results = hybrid_search_qdrant(
        dense_query_vector,
        sparse_query_vector,
        qdrant_client,
        collection_name,
        limit=50,
    )

    # Extract ground truth
    ground_truth_doc_ids = extract_ground_truth_doc_ids(question)

    # Evaluate
    eval_result = evaluate_search_results(search_results, ground_truth_doc_ids)

    return {
        "question_uid": question.uid,
        "question": question.question,
        "ground_truth_doc_ids": list(ground_truth_doc_ids),
        **eval_result,
    }


def main():
    collection_name = CollectionName.ACCURACY_TESTING
    cohere_model = "embed-english-v3.0"
    sparse_model_name = "Qdrant/bm25"
    max_workers = 10  # Number of parallel workers

    # Load environment variables from .env file
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".vscode" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from {env_path}")
    else:
        print(f"Warning: .env file not found at {env_path}")

    # Initialize clients
    print("Initializing clients and embedding models...")
    cohere_api_key = os.getenv("COHERE_API_KEY")
    if not cohere_api_key:
        raise ValueError("COHERE_API_KEY environment variable not set")

    cohere_client = cohere.Client(cohere_api_key)
    qdrant_client = QdrantClient()
    sparse_embedding_model = SparseTextEmbedding(
        model_name=sparse_model_name, threads=2
    )
    print("Clients and models initialized\n")

    # Load questions
    jsonl_path = Path(__file__).parent / "target_questions.jsonl"
    print(f"Loading questions from {jsonl_path}...")
    questions = load_questions(jsonl_path)
    print(f"Loaded {len(questions):,} questions\n")

    # Run evaluation
    print("=" * 80)
    print(f"EVALUATION STARTED (using {max_workers} parallel workers)")
    print("=" * 80)
    print()

    results = []
    start_time = time.time()
    completed = 0

    # Process questions in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_question = {
            executor.submit(
                evaluate_single_question,
                question,
                cohere_client,
                sparse_embedding_model,
                qdrant_client,
                collection_name,
                cohere_model,
            ): question
            for question in questions
        }

        # Process completed tasks as they finish
        for future in as_completed(future_to_question):
            completed += 1
            result = future.result()
            results.append(result)

            # Print progress every 10 questions
            if completed % 10 == 0:
                elapsed = time.time() - start_time
                avg_time = elapsed / completed
                remaining = (len(questions) - completed) * avg_time
                print(
                    f"Progress: {completed}/{len(questions)} ({completed / len(questions) * 100:.1f}%) | "
                    f"Elapsed: {elapsed:.1f}s | ETA: {remaining:.1f}s"
                )

    total_time = time.time() - start_time

    # Calculate aggregate metrics
    print()
    print("=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    print()

    top_1_accuracy = sum(r["top_1_hit"] for r in results) / len(results) * 100
    top_3_accuracy = sum(r["top_3_hit"] for r in results) / len(results) * 100
    top_5_accuracy = sum(r["top_5_hit"] for r in results) / len(results) * 100
    top_10_accuracy = sum(r["top_10_hit"] for r in results) / len(results) * 100
    mrr = sum(r["reciprocal_rank"] for r in results) / len(results)

    # Calculate average recall at different k values
    avg_recall_at_1 = sum(r["recall_at_1"] for r in results) / len(results) * 100
    avg_recall_at_3 = sum(r["recall_at_3"] for r in results) / len(results) * 100
    avg_recall_at_5 = sum(r["recall_at_5"] for r in results) / len(results) * 100
    avg_recall_at_10 = sum(r["recall_at_10"] for r in results) / len(results) * 100
    avg_recall_at_25 = sum(r["recall_at_25"] for r in results) / len(results) * 100
    avg_recall_at_50 = sum(r["recall_at_50"] for r in results) / len(results) * 100

    print(f"Total questions evaluated: {len(results):,}")
    print(f"Total time: {total_time:.2f}s ({total_time / 60:.1f} minutes)")
    print(f"Average time per query: {total_time / len(results):.2f}s")
    print()

    print("Perfect Recall Accuracy (all ground truth docs found):")
    print(f"  Top-1 Accuracy:  {top_1_accuracy:.2f}%")
    print(f"  Top-3 Accuracy:  {top_3_accuracy:.2f}%")
    print(f"  Top-5 Accuracy:  {top_5_accuracy:.2f}%")
    print(f"  Top-10 Accuracy: {top_10_accuracy:.2f}%")
    print()

    print("Average Found Ratio (recall metrics):")
    print(f"  Average found ratio in first 1 context docs:  {avg_recall_at_1:.2f}%")
    print(f"  Average found ratio in first 3 context docs:  {avg_recall_at_3:.2f}%")
    print(f"  Average found ratio in first 5 context docs:  {avg_recall_at_5:.2f}%")
    print(f"  Average found ratio in first 10 context docs: {avg_recall_at_10:.2f}%")
    print(f"  Average found ratio in first 25 context docs: {avg_recall_at_25:.2f}%")
    print(f"  Average found ratio in first 50 context docs: {avg_recall_at_50:.2f}%")
    print()

    print(f"MRR (Mean Reciprocal Rank): {mrr:.4f}")
    print()

    # Show some examples
    print("=" * 80)
    print("SAMPLE RESULTS (First 2)")
    print("=" * 80)
    print()

    for idx, result in enumerate(results[:2], start=1):
        print(f"{idx}. Question: {result['question']}")
        print(
            f"   Ground truth: {result['ground_truth_doc_ids']} ({result['num_ground_truth']} docs)"
        )
        print(
            f"   Recall@3: {result['recall_at_3'] * 100:.0f}% | Recall@5: {result['recall_at_5'] * 100:.0f}% |"
            f"   Recall@10: {result['recall_at_10'] * 100:.0f}%"
        )
        print(
            f"   First correct rank: {result['first_correct_rank'] if result['first_correct_rank'] else 'Not found'}"
        )
        print(f"   Deduplicated top 5: {result['deduplicated_doc_ids'][:5]}")
        print()

    # Show multi-document ground truth examples
    print("=" * 80)
    print("MULTI-DOCUMENT GROUND TRUTH SAMPLES")
    print("=" * 80)
    print()

    multi_doc_results = [r for r in results if len(r["ground_truth_doc_ids"]) > 1]
    if multi_doc_results:
        print(
            f"Found {len(multi_doc_results)} questions with multiple ground truth documents\n"
        )

        for idx, result in enumerate(multi_doc_results[:2], start=1):
            print(f"{idx}. Question: {result['question']}")
            print(f"   # of ground truth docs: {result['num_ground_truth']}")
            print(f"   Ground truth doc IDs: {result['ground_truth_doc_ids']}")
            print(
                f"   Recall@1: {result['recall_at_1'] * 100:.0f}% | Recall@3: {result['recall_at_3'] * 100:.0f}% | Recall@5: "
                f"{result['recall_at_5'] * 100:.0f}% | Recall@10: {result['recall_at_10'] * 100:.0f}%"
            )
            print(
                f"   Perfect recall in top-3: {'✓' if result['top_3_hit'] else '✗'} | "
                f"top-5: {'✓' if result['top_5_hit'] else '✗'} | top-10: {'✓' if result['top_10_hit'] else '✗'}"
            )
            print(
                f"   First correct rank: {result['first_correct_rank'] if result['first_correct_rank'] else 'Not found'}"
            )
            print(f"   Deduplicated (top 10): {result['deduplicated_doc_ids'][:10]}")
            print()
    else:
        print("No questions with multiple ground truth documents found.\n")

    # Save detailed results to file
    output_path = Path(__file__).parent / "evaluation_results.json"
    with open(output_path, "w") as f:
        json.dump(
            {
                "summary": {
                    "total_questions": len(results),
                    "total_multi_doc_questions": len(multi_doc_results),
                    "perfect_recall_accuracy": {
                        "top_1": top_1_accuracy,
                        "top_3": top_3_accuracy,
                        "top_5": top_5_accuracy,
                        "top_10": top_10_accuracy,
                    },
                    "average_recall": {
                        "recall_at_1": avg_recall_at_1,
                        "recall_at_3": avg_recall_at_3,
                        "recall_at_5": avg_recall_at_5,
                        "recall_at_10": avg_recall_at_10,
                        "recall_at_25": avg_recall_at_25,
                        "recall_at_50": avg_recall_at_50,
                    },
                    "mrr": mrr,
                    "total_time_seconds": total_time,
                    "avg_time_per_query_seconds": total_time / len(results),
                },
                "detailed_results": results,
            },
            f,
            indent=2,
        )

    print(f"Detailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
