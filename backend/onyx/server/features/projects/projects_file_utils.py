from contextlib import suppress
from io import BytesIO
from math import ceil

from fastapi import UploadFile
from PIL import Image
from PIL import ImageOps
from PIL import UnidentifiedImageError
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.extract_file_text import ExtractionResult
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.llm.factory import get_default_llm
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SKIP_USERFILE_THRESHOLD
from shared_configs.configs import SKIP_USERFILE_THRESHOLD_TENANT_LIST
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()
FILE_TOKEN_COUNT_THRESHOLD = 100000
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


def estimate_image_tokens(
    image_data: bytes,
    cap_long_side: int = 2048,
    patch_size: int = 16,
    overhead_tokens: int = 32,
) -> int:
    """Estimate tokens for an image from raw bytes.

    Opens the image, normalizes orientation, caps the long side, and estimates tokens.

    Parameters
    - cap_long_side: Maximum pixels allowed on the image's longer side before estimating.
      Rationale: Many vision-language encoders downsample images so the longer side is
      bounded (commonly around 1024-2048px). Capping avoids unbounded patch counts and
      keeps costs predictable while preserving most semantic content for typical UI/docs.
      Default 2048 is a balanced choice between fidelity and token cost.

    - patch_size: The pixel size of square patches used in a rough ViT-style estimate.
      Rationale: Modern vision backbones (e.g., ViT variants) commonly operate on 14-16px
      patches. Using 16 simplifies the estimate and aligns with widely used configurations.
      Each patch approximately maps to one visual token in this heuristic.

    - overhead_tokens: Fixed per-image overhead to account for special tokens, metadata,
      and prompt framing added by providers. Rationale: Real models add tens of tokens per
      image beyond pure patch count. 32 is a conservative, stable default that avoids
      undercounting.

    Notes
    - This is a heuristic estimation for budgeting and gating. Actual tokenization varies
      by model/provider and may differ slightly.
    """
    img = Image.open(BytesIO(image_data))
    img = ImageOps.exif_transpose(img)
    width, height = img.size

    capped_w, capped_h = _apply_long_side_cap(width, height, cap=cap_long_side)
    patches_w = ceil(capped_w / patch_size)
    patches_h = ceil(capped_h / patch_size)

    patches = patches_w * patches_h

    return patches + overhead_tokens


def categorize_uploaded_files(files: list[UploadFile]) -> CategorizedFiles:
    """
    Categorize uploaded files based on text extractability and tokenized length.

    - Extracts text using extract_file_text for supported plain/document extensions.
    - Uses default tokenizer to compute token length.
    - If token length > 100,000, marked as non_accepted (unless threshold skip is enabled).
    - If extension unsupported or text cannot be extracted, marked as unsupported.
    - Otherwise marked as acceptable.
    """

    results = CategorizedFiles()
    llm = get_default_llm()

    tokenizer = get_tokenizer(
        model_name=llm.config.model_name, provider_type=llm.config.model_provider
    )

    # Check if threshold checks should be skipped
    skip_threshold = False

    # Check global skip flag (works for both single-tenant and multi-tenant)
    if SKIP_USERFILE_THRESHOLD:
        skip_threshold = True
        logger.info("Skipping userfile threshold check (global setting)")
    # Check tenant-specific skip list (only applicable in multi-tenant)
    elif MULTI_TENANT and SKIP_USERFILE_THRESHOLD_TENANT_LIST:
        try:
            current_tenant_id = get_current_tenant_id()
            skip_threshold = current_tenant_id in SKIP_USERFILE_THRESHOLD_TENANT_LIST
            if skip_threshold:
                logger.info(
                    f"Skipping userfile threshold check for tenant: {current_tenant_id}"
                )
        except RuntimeError as e:
            logger.warning(f"Failed to get current tenant ID: {str(e)}")

    for upload in files:
        try:
            filename = get_safe_filename(upload)
            extension = get_file_ext(filename)
            token_count = 0

            if extension not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
                raise ValueError("Unsupported file extension")

            # If image, estimate tokens via dedicated method first
            if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
                image_data = upload.file.read()
                token_count = estimate_image_tokens(image_data)

            # Otherwise, handle document as we would in file connector
            elif extension in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
                # Use image_callback to count tokens as images are extracted,
                # avoiding holding all images in memory (OOM risk)
                embedded_image_tokens = 0

                def count_embedded_image_tokens(img_data: bytes, _: str) -> None:
                    nonlocal embedded_image_tokens
                    try:
                        embedded_image_tokens += estimate_image_tokens(img_data)
                    except (UnidentifiedImageError, OSError) as e:
                        logger.warning(
                            f"Failed to estimate tokens for embedded image "
                            f"from '{filename}': {e}"
                        )

                extraction_result: ExtractionResult = extract_text_and_images(
                    file=upload.file,
                    file_name=filename,
                    content_type=upload.content_type,
                    image_callback=count_embedded_image_tokens,
                )

                text_token_count = (
                    len(tokenizer.encode(extraction_result.text_content))
                    if extraction_result.text_content
                    else 0
                )

                token_count = text_token_count + embedded_image_tokens

            if not skip_threshold and token_count > FILE_TOKEN_COUNT_THRESHOLD:
                logger.warning(
                    f"User uploaded file '{filename}' has too many tokens: {token_count}, skipping"
                )
                results.non_accepted.append(filename)
            elif token_count == 0:
                logger.warning(
                    f"User uploaded file '{filename}' has no content, skipping"
                )
                results.unsupported.append(filename)
            else:
                results.acceptable.append(upload)
                results.acceptable_file_to_token_count[filename] = token_count
        except Exception as e:
            logger.warning(
                f"Failed to process uploaded file '{get_safe_filename(upload)}' (error_type={type(e).__name__}, error={str(e)})"
            )
            results.unsupported.append(get_safe_filename(upload))
        finally:
            with suppress(Exception):  # Always attempt to reset the file pointer
                upload.file.seek(0)

    return results
