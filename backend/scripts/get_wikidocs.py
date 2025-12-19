#!/usr/bin/env python3
"""
Script to pull Wikipedia documents from Hugging Face and organize them into zip files.

Usage:
    python get_wikidocs.py --total 1000 --per-zip 100 --output ./wikidata_zips
"""

import argparse
import os
import re
import zipfile
from pathlib import Path

from datasets import load_dataset  # type: ignore
from tqdm import tqdm  # type: ignore


def sanitize_filename(title: str) -> str:
    """
    Sanitize a title for use as a filename.

    - Remove special characters
    - Replace whitespaces with underscores
    - Limit length to avoid filesystem issues

    Args:
        title: The Wikipedia page title

    Returns:
        Sanitized filename string
    """
    # Replace whitespace with underscores
    sanitized = re.sub(r"\s+", "_", title)

    # Remove special characters, keep alphanumeric, underscores, and hyphens
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "", sanitized)

    # Limit length to 200 characters to avoid filesystem issues
    if len(sanitized) > 200:
        sanitized = sanitized[:200]

    # Ensure it's not empty after sanitization
    if not sanitized:
        sanitized = "untitled"

    return sanitized


def stream_wikipedia_to_zips(
    total_pages: int,
    pages_per_zip: int,
    output_dir: str = ".",
    dataset_name: str = "wikipedia",
    dataset_config: str = "20220301.en",
) -> None:
    """
    Stream Wikipedia pages from Hugging Face and write them to zip files.

    Args:
        total_pages: Total number of Wikipedia pages to download
        pages_per_zip: Number of pages to include in each zip file
        output_dir: Directory where zip files will be saved
        dataset_name: Name of the dataset on Hugging Face
        dataset_config: Configuration/version of the dataset
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("Loading Wikipedia dataset from Hugging Face (streaming mode)...")
    print(f"Dataset: {dataset_name}, Config: {dataset_config}")

    # Load dataset in streaming mode
    dataset = load_dataset(
        dataset_name,
        dataset_config,
        split="train",
        streaming=True,
        trust_remote_code=True,
    )

    # Initialize counters
    current_zip_index = 0
    pages_in_current_zip = 0
    current_zip = None
    zip_path = None

    # Process pages with progress bar
    with tqdm(total=total_pages, desc="Processing Wikipedia pages") as pbar:
        for idx, page in enumerate(dataset):
            if idx >= total_pages:
                break

            # Create new zip file if needed
            if pages_in_current_zip == 0 or pages_in_current_zip >= pages_per_zip:
                # Close previous zip if exists
                if current_zip is not None:
                    current_zip.close()
                    print(f"\nCompleted: {zip_path} ({pages_in_current_zip} pages)")

                # Create new zip
                zip_path = output_path / f"wiki_data_{current_zip_index}.zip"
                current_zip = zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED)
                current_zip_index += 1
                pages_in_current_zip = 0

            # Extract page data
            title = page.get("title", f"page_{idx}")
            text = page.get("text", "")

            # Create sanitized filename
            filename = f"{sanitize_filename(title)}.txt"

            # Ensure current_zip is not None (should always be created in the if block above)
            if current_zip is None:
                raise RuntimeError("Zip file was not properly initialized")

            # Handle potential duplicate filenames within the same zip
            base_filename = filename
            counter = 1
            while filename in current_zip.namelist():
                name, ext = os.path.splitext(base_filename)
                filename = f"{name}_{counter}{ext}"
                counter += 1

            # Write page content to zip
            page_content = f"Title: {title}\n\n{text}"
            current_zip.writestr(filename, page_content)

            pages_in_current_zip += 1
            pbar.update(1)

    # Close final zip file
    if current_zip is not None:
        current_zip.close()
        print(f"\nCompleted: {zip_path} ({pages_in_current_zip} pages)")

    print(f"\nSuccessfully created {current_zip_index} zip file(s) in {output_dir}")
    print(f"Total pages processed: {min(total_pages, idx + 1)}")


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Pull Wikipedia documents from Hugging Face and organize into zip files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--total",
        type=int,
        required=True,
        help="Total number of Wikipedia pages to download",
    )

    parser.add_argument(
        "--per-zip",
        type=int,
        required=True,
        help="Number of pages to include in each zip file",
    )

    parser.add_argument(
        "--output", type=str, default=".", help="Output directory for zip files"
    )

    parser.add_argument(
        "--dataset",
        type=str,
        default="wikipedia",
        help="Name of the Wikipedia dataset on Hugging Face",
    )

    parser.add_argument(
        "--config",
        type=str,
        default="20220301.en",
        help="Dataset configuration (e.g., '20220301.en' for English Wikipedia from March 2022)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.total <= 0:
        parser.error("--total must be a positive integer")

    if args.per_zip <= 0:
        parser.error("--per-zip must be a positive integer")

    print("=" * 70)
    print("Wikipedia Data Extractor")
    print("=" * 70)
    print(f"Total pages: {args.total}")
    print(f"Pages per zip: {args.per_zip}")
    print(f"Output directory: {args.output}")
    print(f"Expected zip files: {(args.total + args.per_zip - 1) // args.per_zip}")
    print("=" * 70)
    print()

    try:
        stream_wikipedia_to_zips(
            total_pages=args.total,
            pages_per_zip=args.per_zip,
            output_dir=args.output,
            dataset_name=args.dataset,
            dataset_config=args.config,
        )
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
