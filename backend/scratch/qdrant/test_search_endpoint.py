"""
Test script to verify Qdrant search functionality directly.
"""

import time

from onyx.server.qdrant_search.service import search_documents


def test_search():
    """Test the search functionality with timing."""
    test_queries = [
        "docker",
        "kubernetes",
        "container orchestration",
        "how to install",
    ]

    print("=" * 80)
    print("TESTING QDRANT SEARCH FUNCTIONALITY")
    print("=" * 80)

    for query in test_queries:
        print(f"\n\nQuery: '{query}'")
        print("-" * 80)

        start_time = time.time()
        try:
            response = search_documents(query=query, limit=3)
            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds

            print(f"✓ Search completed in {elapsed_time:.2f}ms")
            print(f"Total results: {response.total_results}")

            for i, result in enumerate(response.results, 1):
                print(f"\n  Result {i}:")
                print(f"    Score: {result.score:.4f}")
                print(f"    Source: {result.source_type or 'N/A'}")
                print(f"    Filename: {result.filename or 'N/A'}")
                print(f"    Content preview: {result.content[:100]}...")

        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            print(f"✗ Search failed after {elapsed_time:.2f}ms")
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    test_search()
