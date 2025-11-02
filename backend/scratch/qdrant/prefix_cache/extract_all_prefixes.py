"""
Extract ALL prefixes from the target_docs.jsonl corpus at scale (100k+).

Strategy:
1. Extract tokens from filenames, URLs, document IDs
2. Extract ALL words from content (not just top N)
3. Generate prefixes for everything (1-10 characters)
4. Target: 100k+ unique prefixes
"""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def extract_tokens_from_filename(filename: str | None) -> list[str]:
    """Extract searchable tokens from filename."""
    if not filename:
        return []

    # Remove extension
    name_without_ext = re.sub(r"\.[^.]+$", "", filename)

    # Split on common separators: _, -, ~, space, .
    tokens = re.split(r"[_\-~\s.]+", name_without_ext.lower())

    # Filter out empty, very short tokens, and non-ASCII
    tokens = [t for t in tokens if len(t) >= 3 and t.isascii()]

    return tokens


def extract_tokens_from_url(url: str | None) -> list[str]:
    """Extract searchable tokens from URL."""
    if not url:
        return []

    try:
        parsed = urlparse(url)

        # Get domain parts
        domain_parts = parsed.netloc.lower().split(".")

        # Get path parts
        path_parts = [p for p in parsed.path.lower().split("/") if p]

        all_parts = domain_parts + path_parts

        # Further split on common separators
        tokens = []
        for part in all_parts:
            tokens.extend(re.split(r"[_\-~\s.]+", part))

        # Filter
        tokens = [t for t in tokens if len(t) >= 3]

        return tokens
    except Exception:
        return []


def extract_words_from_text(text: str) -> list[str]:
    """Extract ALL words from text (no stop word filtering for max coverage)."""
    # Remove URLs, email addresses
    text = re.sub(r"http[s]?://\S+", "", text)
    text = re.sub(r"\S+@\S+", "", text)

    # Extract words (3+ characters, ASCII letters only - NO NUMBERS, NO UNICODE)
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())

    # Filter out any non-ASCII words
    ascii_words = [w for w in words if w.isascii()]

    return ascii_words


def generate_prefixes(word: str, min_len: int = 1, max_len: int = 10) -> list[str]:
    """Generate all prefixes of a word from min_len to max_len."""
    prefixes = []
    for length in range(min_len, min(len(word), max_len) + 1):
        prefix = word[:length]
        # Only include if it starts with a letter (no numbers or special chars)
        if prefix and prefix[0].isalpha():
            prefixes.append(prefix)
    return prefixes


def main():
    jsonl_path = Path(__file__).parent.parent / "accuracy_testing" / "target_docs.jsonl"

    print("=" * 80)
    print("EXTRACTING ALL PREFIXES AT SCALE")
    print("=" * 80)
    print(f"\nAnalyzing corpus: {jsonl_path}")
    print("Target: 100k+ unique prefixes\n")

    # Collect ALL unique tokens
    all_tokens = set()
    doc_count = 0

    print("Phase 1: Extracting tokens...")
    with open(jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue

            doc = json.loads(line)

            # Extract from filename
            filename = doc.get("filename")
            if filename:
                all_tokens.update(extract_tokens_from_filename(filename))

            # Extract from URL
            url = doc.get("url")
            if url:
                all_tokens.update(extract_tokens_from_url(url))

            # Extract from document_id
            doc_id = doc.get("document_id", "")
            if doc_id:
                # Split on common separators
                id_tokens = re.split(r"[_\-~\s.]+", doc_id.lower())
                all_tokens.update([t for t in id_tokens if len(t) >= 3])

            # Extract from ALL documents (not sampling) to get comprehensive coverage
            content = doc.get("content", "")
            title = doc.get("title", "")
            full_text = f"{title} {content}"
            all_tokens.update(extract_words_from_text(full_text))

            doc_count += 1

            if doc_count % 1000 == 0:
                print(
                    f"  Processed {doc_count:,} documents, {len(all_tokens):,} unique tokens..."
                )

    print(f"\n✓ Processed {doc_count:,} documents")
    print(f"✓ Found {len(all_tokens):,} unique tokens")

    # Generate prefixes from all tokens WITH FREQUENCY TRACKING
    print("\nPhase 2: Generating prefixes with frequency...")
    prefix_frequency = Counter()

    for token in all_tokens:
        # Generate prefixes 1-5 chars (only alphabetic)
        prefixes = generate_prefixes(token, min_len=1, max_len=5)
        for prefix in prefixes:
            prefix_frequency[prefix] += 1

    print(
        f"✓ Generated {len(prefix_frequency):,} unique prefixes (1-5 chars, letters only)"
    )

    # Group by length
    by_length = {}
    for prefix, freq in prefix_frequency.items():
        length = len(prefix)
        if length not in by_length:
            by_length[length] = []
        by_length[length].append((prefix, freq))

    print("\nPrefix distribution (total available):")
    for length in sorted(by_length.keys()):
        print(f"  {length}-char: {len(by_length[length]):,}")

    # Select most POPULAR prefixes from each length category
    # Strategy: Take ALL 1-2 char, then most popular 3-5 char to reach ~10k
    target_count = 10000
    selected = []

    # All 1-char (always useful)
    if 1 in by_length:
        selected.extend([p for p, f in by_length[1]])
        print(f"\nTaking all {len(by_length[1])} 1-char prefixes")

    # All 2-char (very useful)
    if 2 in by_length:
        selected.extend([p for p, f in by_length[2]])
        print(f"Taking all {len(by_length[2])} 2-char prefixes")

    # Calculate remaining budget
    remaining = target_count - len(selected)
    print(f"Remaining budget: {remaining:,} prefixes for 3-5 char")

    # Distribute remaining across 3-5 char based on frequency
    # Weight: 25% for 3-char, 35% for 4-char, 40% for 5-char
    weights = {3: 0.25, 4: 0.35, 5: 0.40}

    for length in [3, 4, 5]:
        if length in by_length:
            take_count = int(remaining * weights[length])
            # Sort by frequency (most popular first)
            sorted_by_freq = sorted(by_length[length], key=lambda x: x[1], reverse=True)
            top_prefixes = [p for p, f in sorted_by_freq[:take_count]]
            selected.extend(top_prefixes)
            print(
                f"Taking top {len(top_prefixes):,} most popular {length}-char prefixes"
            )

    # Sort alphabetically
    sorted_prefixes = sorted(selected)

    print(f"\n✓ Selected {len(sorted_prefixes):,} prefixes for cache")
    for length in range(1, 6):
        count = sum(1 for p in sorted_prefixes if len(p) == length)
        print(f"  {length}-char: {count:,}")

    # Save to file
    output_path = Path(__file__).parent / "corpus_prefixes_100k.txt"
    with open(output_path, "w") as f:
        for prefix in sorted_prefixes:
            f.write(f"{prefix}\n")

    print(f"\n✓ Saved {len(sorted_prefixes):,} prefixes to: {output_path}")

    # Statistics by length
    print("\nPrefix statistics by length:")
    for length in range(1, 11):
        count = sum(1 for p in sorted_prefixes if len(p) == length)
        print(f"  {length}-char: {count:,}")

    # Sample prefixes
    print("\nSample prefixes (first 100):")
    for i, prefix in enumerate(sorted_prefixes[:100], 1):
        print(f"  {i:3d}. '{prefix}'")

    print("\n" + "=" * 80)
    print(f"COMPLETE - {len(sorted_prefixes):,} prefixes extracted")
    print("=" * 80)


if __name__ == "__main__":
    main()
