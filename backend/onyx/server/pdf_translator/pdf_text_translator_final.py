#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import re
import sys
import tempfile
from typing import Dict, List

import fitz  # PyMuPDF

# --- OpenAI translation ---
try:
    from openai import AsyncOpenAI  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'openai' package is required for translation. Install it with 'pip install openai' inside your venv."
    ) from exc

import pdfplumber

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Obtain the API key from environment variable
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError(
        "OPENAI_API_KEY environment variable not set. Please export it before running the script."
    )

client = AsyncOpenAI(api_key=api_key)

# Rate limiting settings
MAX_CONCURRENT_REQUESTS = 30  # Maximum number of concurrent API calls
RATE_LIMIT_DELAY = 0.1  # Delay between batches in seconds


class PDFTextTranslatorFinal:
    """Final PDF text translator with exact size preservation and overlap prevention."""

    def __init__(self):
        self._translation_cache = {}
        # Track inserted text regions to prevent overlap
        self._inserted_regions = []
        self._translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    def remove_text_from_pdf(self, input_pdf_path: str, output_pdf_path: str) -> None:
        """Remove all text from PDF while preserving other elements."""
        logger.info(f"Starting PDF text removal: {input_pdf_path} -> {output_pdf_path}")

        doc = fitz.open(input_pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Get all text instances and remove them cleanly
            text_instances = page.get_text("dict")

            for block in text_instances.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            bbox = span.get("bbox")
                            if bbox:
                                # Remove text by adding a redaction annotation WITHOUT fill
                                rect = fitz.Rect(bbox)
                                page.add_redact_annot(rect)

            # Apply redactions to remove text
            page.apply_redactions()

        doc.save(output_pdf_path)
        doc.close()
        logger.info(f"PDF text removal completed successfully: {output_pdf_path}")

    def _parse_font_properties(self, fontname: str) -> dict:
        """Extract font properties from fontname string."""
        properties = {"is_bold": False, "is_italic": False, "base_font": fontname}

        if not fontname:
            return properties

        # Common patterns for bold fonts
        bold_patterns = [
            r"-Bold",
            r"Bold",
            r"-Bd",
            r"Bd",
            r"-Heavy",
            r"Heavy",
            r"-Black",
            r"Black",
            r"-Semibold",
            r"Semibold",
            r"-Medium",
            r"Medium",
        ]

        # Common patterns for italic fonts
        italic_patterns = [
            r"-Italic",
            r"Italic",
            r"-It",
            r"It",
            r"-Oblique",
            r"Oblique",
            r"-Slanted",
            r"Slanted",
        ]

        fontname_lower = fontname.lower()

        # Check for bold
        for pattern in bold_patterns:
            if re.search(pattern.lower(), fontname_lower):
                properties["is_bold"] = True
                break

        # Check for italic
        for pattern in italic_patterns:
            if re.search(pattern.lower(), fontname_lower):
                properties["is_italic"] = True
                break

        return properties

    def _get_text_metrics(
        self, text: str, font_size: float, is_bold: bool = False
    ) -> dict:
        """Get accurate text metrics including width and height."""
        # More accurate character width calculations
        width = 0
        for char in text:
            if char.isdigit():
                width += font_size * 0.5
            elif char in ".,":
                width += font_size * 0.3
            elif char in " ":
                width += font_size * 0.25
            elif char.isupper():
                width += font_size * 0.65
            elif char in "mwMW":
                width += font_size * 0.8
            elif char in "iltI1":
                width += font_size * 0.3
            else:
                width += font_size * 0.5

        # Bold text is wider
        if is_bold:
            width *= 1.15

        # Height is typically 1.2x font size for line spacing
        height = font_size * 1.2

        return {"width": width, "height": height}

    def _is_overlapping(self, rect1, existing_regions, margin=2):
        """Check if rect1 overlaps with any existing regions."""
        x0, y0, x1, y1 = rect1

        for region in existing_regions:
            rx0, ry0, rx1, ry1 = region

            # Check for overlap with margin
            if not (
                x1 + margin < rx0
                or x0 - margin > rx1
                or y1 + margin < ry0
                or y0 - margin > ry1
            ):
                return True

        return False

    def _is_same_line(self, char1, char2, tolerance=1.5):
        """Check if two characters are on the same line with tighter tolerance."""
        if not char1 or not char2:
            return False
        return abs(char1["top"] - char2["top"]) <= tolerance

    def _group_chars_into_lines(self, chars):
        """Group characters into lines with better precision."""
        if not chars:
            return []

        # Sort by position
        chars_sorted = sorted(chars, key=lambda c: (round(c["top"], 2), c["x0"]))

        lines = []
        current_line = []

        for char in chars_sorted:
            if not current_line:
                current_line.append(char)
            elif self._is_same_line(current_line[-1], char):
                current_line.append(char)
            else:
                if current_line:
                    lines.append(current_line)
                current_line = [char]

        if current_line:
            lines.append(current_line)

        return lines

    def _group_line_into_phrases(self, line_chars):
        """Group characters in a line into phrases with improved logic."""
        if not line_chars:
            return []

        # Sort by x position
        line_chars_sorted = sorted(line_chars, key=lambda c: c["x0"])

        phrases = []
        current_phrase = []

        # Calculate average character width
        char_widths = []
        for char in line_chars_sorted:
            if char.get("x1") and char.get("x0") and char["text"].strip():
                char_widths.append(char["x1"] - char["x0"])

        avg_char_width = sum(char_widths) / len(char_widths) if char_widths else 5

        # Dynamic gap threshold based on character width
        gap_threshold = avg_char_width * 2.0  # Slightly larger for better grouping

        for i, char in enumerate(line_chars_sorted):
            if not current_phrase:
                current_phrase.append(char)
            else:
                prev_char = current_phrase[-1]
                gap = char["x0"] - prev_char.get("x1", prev_char["x0"])

                # Check various breaking conditions
                should_break = False

                # Large gap
                if gap > gap_threshold:
                    should_break = True

                # Tab-like gap (very large)
                elif gap > avg_char_width * 5:
                    should_break = True

                # Special handling for table cells - look for vertical alignment patterns
                elif gap > avg_char_width * 3 and len(current_phrase) > 2:
                    should_break = True

                if should_break:
                    phrases.append(current_phrase)
                    current_phrase = [char]
                else:
                    current_phrase.append(char)

            # Check for phrase-ending punctuation
            if char["text"] in ".:;!?" and i < len(line_chars_sorted) - 1:
                next_char = line_chars_sorted[i + 1]
                if char["x1"] < next_char["x0"] - avg_char_width:
                    phrases.append(current_phrase)
                    current_phrase = []

        if current_phrase:
            phrases.append(current_phrase)

        return phrases

    def _extract_phrase_formatting(self, phrase_chars):
        """Extract formatting with exact size preservation."""
        if not phrase_chars:
            return None

        # Filter out empty characters
        non_empty_chars = [c for c in phrase_chars if c.get("text", "").strip()]
        if not non_empty_chars:
            return None

        # Use first non-empty character for formatting
        first_char = non_empty_chars[0]
        non_empty_chars[-1]

        # Calculate precise bounding box
        min_x0 = min(c["x0"] for c in phrase_chars)
        max_x1 = max(c.get("x1", c["x0"]) for c in phrase_chars)
        min_top = min(c["top"] for c in phrase_chars)
        max_bottom = max(c["bottom"] for c in phrase_chars)

        # Get exact font size - no modification
        original_font_size = first_char.get("size", 12)

        formatting = {
            "font_size": original_font_size,  # Exact size
            "fontname": first_char.get("fontname", ""),
            "x0": min_x0,
            "x1": max_x1,
            "top": min_top,
            "bottom": max_bottom,
            "height": max_bottom - min_top,
            "width": max_x1 - min_x0,
            "baseline": first_char["bottom"],
            "original_size": original_font_size,  # Store original for reference
        }

        # Parse font properties
        font_props = self._parse_font_properties(formatting["fontname"])
        formatting.update(font_props)

        # Default to black color
        formatting["color"] = (0, 0, 0)

        return formatting

    async def _translate_batch(self, texts: List[str]) -> Dict[str, str]:
        """Translate a batch of texts in parallel."""
        if not texts:
            return {}

        # Filter out empty texts and check cache
        texts_to_translate = []
        results = {}

        for text in texts:
            if not text.strip():
                results[text] = text
                continue

            cached = self._translation_cache.get(text)
            if cached is not None:
                results[text] = cached
            else:
                texts_to_translate.append(text)

        if not texts_to_translate:
            return results

        async def translate_single(text: str) -> tuple[str, str]:
            async with self._translation_semaphore:
                try:
                    response = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a factual translator. Translate all user content to English only. Return only the translated text without additional commentary. Maintain any numbers, codes, dates, or technical identifiers exactly as they appear in the original.",
                            },
                            {"role": "user", "content": text},
                        ],
                        temperature=0.3,
                        max_tokens=200,
                    )

                    translation = response.choices[0].message.content.strip()
                    if not translation:
                        translation = text

                    return text, translation

                except Exception as exc:
                    logger.warning(f"Translation failed for '{text}': {exc}")
                    return text, text

        # Create tasks for all texts
        tasks = [translate_single(text) for text in texts_to_translate]

        # Execute all tasks concurrently
        completed = await asyncio.gather(*tasks)

        # Process results
        for original, translation in completed:
            results[original] = translation
            self._translation_cache[original] = translation

        return results

    async def replace_text_in_pdf_async(
        self, input_pdf_path: str, output_pdf_path: str
    ) -> None:
        """Async version of replace_text_in_pdf."""
        logger.info(
            f"Starting PDF text replacement (translation to English): {input_pdf_path} -> {output_pdf_path}"
        )

        # Step 1: Create background-only PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_bg:
            temp_bg_path = temp_bg.name

        self.remove_text_from_pdf(input_pdf_path, temp_bg_path)

        # Step 2: Open both PDFs for processing
        doc = fitz.open(temp_bg_path)

        with pdfplumber.open(input_pdf_path) as pdf:
            total_phrases = 0
            successful_insertions = 0
            failed_insertions = 0

            for page_num, page in enumerate(pdf.pages):
                logger.info(f"Processing page {page_num + 1}")

                pdf_page = doc[page_num]

                # Reset inserted regions for each page
                self._inserted_regions = []

                # Extract all characters
                chars = page.chars
                logger.info(f"Found {len(chars)} characters on page {page_num + 1}")

                # Group characters into lines
                lines = self._group_chars_into_lines(chars)
                logger.info(f"Grouped into {len(lines)} lines")

                # Collect all phrases for translation
                phrases_to_translate = []
                phrase_info = []

                # Process each line
                for line_idx, line_chars in enumerate(lines):
                    # Group line into phrases
                    phrases = self._group_line_into_phrases(line_chars)

                    for phrase_idx, phrase in enumerate(phrases):
                        if not phrase:
                            continue

                        total_phrases += 1

                        # Extract phrase text
                        phrase_text = "".join([char.get("text", "") for char in phrase])
                        if not phrase_text.strip():
                            continue

                        # Extract formatting
                        formatting = self._extract_phrase_formatting(phrase)
                        if not formatting:
                            continue

                        # Skip invalid dimensions
                        if formatting["width"] <= 0 or formatting["height"] <= 0:
                            logger.debug(
                                f"Skipping phrase with invalid dimensions: {phrase_text}"
                            )
                            continue

                        phrases_to_translate.append(phrase_text)
                        phrase_info.append((phrase_text, formatting))

                # Translate all phrases in parallel
                translations = await self._translate_batch(phrases_to_translate)

                # Process translations and insert text
                for phrase_text, formatting in phrase_info:
                    translated_text = translations[phrase_text]

                    # Get text metrics
                    metrics = self._get_text_metrics(
                        translated_text,
                        formatting["original_size"],
                        formatting["is_bold"],
                    )

                    # Only scale down if absolutely necessary
                    font_size = formatting["original_size"]
                    if metrics["width"] > formatting["width"] * 1.1:  # 10% tolerance
                        scale_factor = formatting["width"] / metrics["width"]
                        font_size = formatting["original_size"] * scale_factor * 0.95
                        font_size = max(font_size, 5.0)  # Minimum readable size

                    # Prepare font
                    fontname = "Helvetica"
                    if formatting["is_bold"] and formatting["is_italic"]:
                        fontname = "Helvetica-BoldOblique"
                    elif formatting["is_bold"]:
                        fontname = "Helvetica-Bold"
                    elif formatting["is_italic"]:
                        fontname = "Helvetica-Oblique"

                    # Calculate insertion rectangle
                    insert_rect = [
                        formatting["x0"],
                        formatting["top"],
                        formatting["x0"] + metrics["width"],
                        formatting["bottom"],
                    ]

                    # Check for overlap
                    if self._is_overlapping(insert_rect, self._inserted_regions):
                        # Try to adjust position slightly
                        logger.debug(
                            f"Overlap detected for '{translated_text[:20]}...', adjusting"
                        )
                        # Try moving down slightly
                        insert_rect[1] += 2
                        insert_rect[3] += 2

                    # Insert text
                    insertion_successful = False

                    try:
                        # For table cells or constrained areas, use textbox
                        if (
                            formatting["width"] < 100
                            or "|" in phrase_text
                            or len(translated_text) > 15
                        ):
                            rect = fitz.Rect(
                                formatting["x0"],
                                formatting["top"],
                                formatting["x1"],
                                formatting["bottom"],
                            )

                            rc = pdf_page.insert_textbox(
                                rect,
                                translated_text,
                                fontsize=font_size,
                                fontname=fontname,
                                color=formatting["color"],
                                align=fitz.TEXT_ALIGN_LEFT,
                                render_mode=0,
                            )

                            if rc >= 0:
                                insertion_successful = True
                                self._inserted_regions.append(insert_rect)
                                logger.debug(
                                    f"Textbox inserted: '{translated_text[:30]}...'"
                                )
                            else:
                                # Text doesn't fit, try smaller font
                                smaller_font = font_size * 0.85
                                rc = pdf_page.insert_textbox(
                                    rect,
                                    translated_text,
                                    fontsize=smaller_font,
                                    fontname=fontname,
                                    color=formatting["color"],
                                    align=fitz.TEXT_ALIGN_LEFT,
                                    render_mode=0,
                                )
                                if rc >= 0:
                                    insertion_successful = True
                                    self._inserted_regions.append(insert_rect)

                        # For regular text, use insert_text
                        if not insertion_successful:
                            insertion_point = (formatting["x0"], formatting["baseline"])

                            pdf_page.insert_text(
                                insertion_point,
                                translated_text,
                                fontsize=font_size,
                                fontname=fontname,
                                color=formatting["color"],
                                render_mode=0,
                            )
                            insertion_successful = True
                            self._inserted_regions.append(insert_rect)
                            logger.debug(f"Text inserted: '{translated_text[:30]}...'")

                    except Exception as e:
                        logger.warning(
                            f"Failed to insert '{translated_text[:30]}...' at "
                            f"({formatting['x0']:.1f}, {formatting['baseline']:.1f}): {e}"
                        )

                        # Last resort with default font
                        try:
                            pdf_page.insert_text(
                                (formatting["x0"], formatting["baseline"]),
                                translated_text,
                                fontsize=font_size,
                                color=formatting["color"],
                                render_mode=0,
                            )
                            insertion_successful = True
                            self._inserted_regions.append(insert_rect)
                        except Exception as e2:
                            logger.error(f"All insertions failed: {e2}")

                    if insertion_successful:
                        successful_insertions += 1
                    else:
                        failed_insertions += 1
                        logger.error(
                            f"Failed to insert: '{phrase_text}' -> '{translated_text}'"
                        )

                logger.info(
                    f"Page {page_num + 1}: {successful_insertions} successful, {failed_insertions} failed"
                )

        # Save the final PDF
        doc.save(output_pdf_path)
        doc.close()

        # Clean up temporary file
        os.unlink(temp_bg_path)

        logger.info("PDF text replacement completed")
        logger.info(f"Total phrases: {total_phrases}")
        logger.info(f"Successful insertions: {successful_insertions}")
        logger.info(f"Failed insertions: {failed_insertions}")

    def replace_text_in_pdf(self, input_pdf_path: str, output_pdf_path: str) -> None:
        """Synchronous wrapper for async PDF text replacement."""
        asyncio.run(self.replace_text_in_pdf_async(input_pdf_path, output_pdf_path))


def main():
    parser = argparse.ArgumentParser(
        description="Final PDF text translator with exact formatting preservation"
    )
    parser.add_argument("input_pdf", help="Input PDF file path")
    parser.add_argument("output_pdf", help="Output PDF file path")
    parser.add_argument(
        "--mode",
        choices=["remove", "translate"],
        default="translate",
        help="Mode: 'remove' to remove text, 'translate' to translate to English",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.exists(args.input_pdf):
        logger.error(f"Input file does not exist: {args.input_pdf}")
        sys.exit(1)

    processor = PDFTextTranslatorFinal()

    try:
        if args.mode == "remove":
            processor.remove_text_from_pdf(args.input_pdf, args.output_pdf)
            print("Text removal completed successfully!")
        else:
            processor.replace_text_in_pdf(args.input_pdf, args.output_pdf)
            print("PDF translation completed successfully!")

        print(f"Input: {args.input_pdf}")
        print(f"Output: {args.output_pdf}")

    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
