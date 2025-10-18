"""
Test script to verify prefix cache performance improvements.
"""

import time

from onyx.server.qdrant_search.service import search_documents


def test_prefix_cache_performance():
    """Test the search functionality with and without prefix caching."""

    # Test queries - mix of cached and uncached
    test_cases = [
        ("docker", "Should HIT cache"),
        ("kubernetes", "Should HIT cache"),
        ("python", "Should HIT cache"),
        ("how to install docker containers", "Should MISS cache"),
        ("docker", "Should HIT cache (2nd time)"),
        ("d", "Should HIT cache (single char)"),
        ("do", "Should HIT cache (2-char)"),
        ("doc", "Should HIT cache (3-char)"),
        ("dock", "Should HIT cache (4-char)"),
        ("container orchestration performance", "Should MISS cache"),
    ]

    print("=" * 80)
    print("PREFIX CACHE PERFORMANCE TEST")
    print("=" * 80)

    results = []

    for query, expected in test_cases:
        print(f"\n\nQuery: '{query}' ({expected})")
        print("-" * 80)

        start_time = time.time()
        try:
            response = search_documents(query=query, limit=3)
            elapsed_ms = (time.time() - start_time) * 1000

            print(f"✓ Search completed in {elapsed_ms:.2f}ms")
            print(f"  Total results: {response.total_results}")

            if response.results:
                print(f"  Top result score: {response.results[0].score:.4f}")

            results.append(
                {
                    "query": query,
                    "time_ms": elapsed_ms,
                    "expected": expected,
                    "num_results": response.total_results,
                }
            )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            print(f"✗ Search failed after {elapsed_ms:.2f}ms")
            print(f"  Error: {e}")
            import traceback

            traceback.print_exc()

    # Summary
    print("\n\n" + "=" * 80)
    print("PERFORMANCE SUMMARY")
    print("=" * 80)

    cache_hits = [r for r in results if "HIT" in r["expected"]]
    cache_misses = [r for r in results if "MISS" in r["expected"]]

    if cache_hits:
        avg_hit_time = sum(r["time_ms"] for r in cache_hits) / len(cache_hits)
        print(f"\nCache HITs (n={len(cache_hits)}): avg {avg_hit_time:.2f}ms")
        for r in cache_hits:
            print(f"  '{r['query']}': {r['time_ms']:.2f}ms")

    if cache_misses:
        avg_miss_time = sum(r["time_ms"] for r in cache_misses) / len(cache_misses)
        print(f"\nCache MISSes (n={len(cache_misses)}): avg {avg_miss_time:.2f}ms")
        for r in cache_misses:
            print(f"  '{r['query']}': {r['time_ms']:.2f}ms")

    if cache_hits and cache_misses:
        speedup = avg_miss_time / avg_hit_time
        print(f"\n📈 Cache speedup: {speedup:.1f}x faster")
        print(f"   Cache hit latency: {avg_hit_time:.2f}ms")
        print(f"   Cache miss latency: {avg_miss_time:.2f}ms")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_prefix_cache_performance()
