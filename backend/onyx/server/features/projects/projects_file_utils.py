from math import ceil

from fastapi import UploadFile
from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.file_processing.extract_file_text import ACCEPTED_IMAGE_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import ALL_ACCEPTED_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.llm.factory import get_default_llms
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger


logger = setup_logger()
FILE_TOKEN_COUNT_THRESHOLD = 50000
UNKNOWN_FILENAME = "[unknown_file]"  # More descriptive than empty string


def get_safe_filename(upload: UploadFile) -> str:
    """Get filename from upload, with fallback to UNKNOWN_FILENAME if None."""
    if not upload.filename:
        logger.warning("Received upload with no filename")
        return UNKNOWN_FILENAME
    return upload.filename


# Guard against extremely large images
Image.MAX_IMAGE_PIXELS = 12000 * 12000


class CategorizedFiles(BaseModel):
    acceptable: list[UploadFile] = Field(default_factory=list)
    non_accepted: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
    acceptable_file_to_token_count: dict[str, int] = Field(default_factory=dict)

    # Allow FastAPI UploadFile instances
    model_config = ConfigDict(arbitrary_types_allowed=True)


def _apply_long_side_cap(width: int, height: int, cap: int) -> tuple[int, int]:
    if max(width, height) <= cap:
        return width, height
    scale = cap / max(width, height)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return new_w, new_h


def _estimate_image_tokens(
    width: int, height: int, patch_size: int, overhead: int
) -> int:
    patches_w = ceil(width / patch_size)
    patches_h = ceil(height / patch_size)
    patches = patches_w * patches_h
    return patches + overhead


def estimate_image_tokens_for_upload(
    upload: UploadFile,
    cap_long_side: int = 2048,
    patch_size: int = 16,
    overhead_tokens: int = 32,
) -> int:
    """Open the uploaded image, normalize orientation, cap long side, and estimate tokens.

    Parameters
    - cap_long_side: Maximum pixels allowed on the image's longer side before estimating.
      Rationale: Many vision-language encoders downsample images so the longer side is
      bounded (commonly around 1024–2048px). Capping avoids unbounded patch counts and
      keeps costs predictable while preserving most semantic content for typical UI/docs.
      Default 2048 is a balanced choice between fidelity and token cost.

    - patch_size: The pixel size of square patches used in a rough ViT-style estimate.
      Rationale: Modern vision backbones (e.g., ViT variants) commonly operate on 14–16px
      patches. Using 16 simplifies the estimate and aligns with widely used configurations.
      Each patch approximately maps to one visual token in this heuristic.

    - overhead_tokens: Fixed per-image overhead to account for special tokens, metadata,
      and prompt framing added by providers. Rationale: Real models add tens of tokens per
      image beyond pure patch count. 32 is a conservative, stable default that avoids
      undercounting.

    Notes
    - This is a heuristic estimation for budgeting and gating. Actual tokenization varies
      by model/provider and may differ slightly.

    Always resets the file pointer before returning.
    """
    try:
        img = Image.open(upload.file)
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        capped_w, capped_h = _apply_long_side_cap(width, height, cap=cap_long_side)
        return _estimate_image_tokens(
            capped_w, capped_h, patch_size=patch_size, overhead=overhead_tokens
        )
    finally:
        try:
            upload.file.seek(0)
        except Exception:
            pass


def categorize_uploaded_files(files: list[UploadFile]) -> CategorizedFiles:
    """
    Categorize uploaded files based on text extractability and tokenized length.

    - Extracts text using extract_file_text for supported plain/document extensions.
    - Uses default tokenizer to compute token length.
    - If token length > 50,000, marked as non_accepted.
    - If extension unsupported or text cannot be extracted, marked as unsupported.
    - Otherwise marked as acceptable.
    """

    results = CategorizedFiles()
    llm, _ = get_default_llms()

    tokenizer = get_tokenizer(
        model_name=llm.config.model_name, provider_type=llm.config.model_provider
    )

    for upload in files:
        try:
            filename = get_safe_filename(upload)
            extension = get_file_ext(filename)

            # If image, estimate tokens via dedicated method first
            if extension in ACCEPTED_IMAGE_FILE_EXTENSIONS:
                try:
                    token_count = estimate_image_tokens_for_upload(upload)
                except (UnidentifiedImageError, OSError) as e:
                    logger.warning(
                        f"Failed to process image file '{filename}': {str(e)}"
                    )
                    results.unsupported.append(filename)
                    continue

                if token_count > FILE_TOKEN_COUNT_THRESHOLD:
                    results.non_accepted.append(filename)
                else:
                    results.acceptable.append(upload)
                    results.acceptable_file_to_token_count[filename] = token_count
                continue

            # Otherwise, handle as text/document: extract text and count tokens
            if (
                extension in ALL_ACCEPTED_FILE_EXTENSIONS
                and extension not in ACCEPTED_IMAGE_FILE_EXTENSIONS
            ):
                text_content = extract_file_text(
                    file=upload.file,
                    file_name=filename,
                    break_on_unprocessable=False,
                    extension=extension,
                )
                if not text_content:
                    logger.warning(f"No text content extracted from '{filename}'")
                    results.unsupported.append(filename)
                    continue

                token_count = len(tokenizer.encode(text_content))
                if token_count > FILE_TOKEN_COUNT_THRESHOLD:
                    results.non_accepted.append(filename)
                else:
                    results.acceptable.append(upload)
                    results.acceptable_file_to_token_count[filename] = token_count

                # Reset file pointer for subsequent upload handling
                try:
                    upload.file.seek(0)
                except Exception as e:
                    logger.warning(
                        f"Failed to reset file pointer for '{filename}': {str(e)}"
                    )
                continue

            # If not recognized as supported types above, mark unsupported
            logger.warning(
                f"Unsupported file extension '{extension}' for file '{filename}'"
            )
            results.unsupported.append(filename)
        except Exception as e:
            logger.warning(
                f"Failed to process uploaded file '{get_safe_filename(upload)}' (error_type={type(e).__name__}, error={str(e)})"
            )
            results.unsupported.append(get_safe_filename(upload))

    return results
