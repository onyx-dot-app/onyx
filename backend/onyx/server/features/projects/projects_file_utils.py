from math import ceil

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from onyx.configs.app_configs import (
    MAX_EMBEDDED_IMAGES_PER_FILE,
    MAX_EMBEDDED_IMAGES_PER_UPLOAD,
)
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_default_model
from onyx.file_processing.extract_file_text import (
    count_docx_embedded_images,
    extract_file_text,
    file_io_to_text,
    get_file_ext,
    is_text_file,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.password_validation import is_file_password_protected
from onyx.file_processing.pdf_image_utils import count_pdf_embedded_images
from onyx.natural_language_processing.utils import (
    BaseTokenizer,
    count_tokens,
    get_tokenizer,
)
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()
UNKNOWN_FILENAME = "[unknown_file]"  # More descriptive than empty string


def get_safe_filename(upload: UploadFile) -> str:
    """Get filename from upload, with fallback to UNKNOWN_FILENAME if None."""
    if not upload.filename:
        logger.warning("Received upload with no filename")
        return UNKNOWN_FILENAME
    return upload.filename


def get_upload_size_bytes(upload: UploadFile) -> int | None:
    """Best-effort file size in bytes without consuming the stream."""
    if upload.size is not None:
        return upload.size

    try:
        current_pos = upload.file.tell()
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(current_pos)
        return size
    except Exception as e:
        logger.warning(
            "Could not determine upload size via stream seek (filename='%s', error_type=%s, error=%s)",
            get_safe_filename(upload),
            type(e).__name__,
            e,
        )
        return None


def is_upload_too_large(upload: UploadFile, max_bytes: int) -> bool:
    """Return True when upload size is known and exceeds max_bytes."""
    size_bytes = get_upload_size_bytes(upload)
    if size_bytes is None:
        logger.warning(
            "Could not determine upload size; skipping size-limit check for '%s'",
            get_safe_filename(upload),
        )
        return False
    return size_bytes > max_bytes


# Guard against extremely large images
Image.MAX_IMAGE_PIXELS = 12000 * 12000


class RejectedFile(BaseModel):
    filename: str = Field(default="")
    reason: str = Field(default="")


class CategorizedFiles(BaseModel):
    acceptable: list[UploadFile] = Field(default_factory=list)
    rejected: list[RejectedFile] = Field(default_factory=list)
    # The token count of each file of `acceptable`, and whether it is
    # stored but not indexed, in order (files of one name keep their own).
    acceptable_token_counts: list[int] = Field(default_factory=list)
    acceptable_skip_indexing: list[bool] = Field(default_factory=list)

    # Allow FastAPI UploadFile instances
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def accept(
        self, upload: UploadFile, token_count: int, *, skip_indexing: bool = False
    ) -> None:
        self.acceptable.append(upload)
        self.acceptable_token_counts.append(token_count)
        self.acceptable_skip_indexing.append(skip_indexing)


def _skip_token_threshold(extension: str) -> bool:
    """Return True if this file extension should bypass the token limit."""
    return extension.lower() in OnyxFileExtensions.TABULAR_EXTENSIONS


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


def _categorize_sandbox_only_file(
    upload: UploadFile,
    filename: str,
    tokenizer: BaseTokenizer,
    token_threshold_k: int | None,
    results: CategorizedFiles,
) -> None:
    """Accept a text code file but flag it to skip indexing."""
    upload.file.seek(0)
    if not is_text_file(upload.file):
        results.rejected.append(
            RejectedFile(filename=filename, reason="Unsupported file contents")
        )
        return
    token_threshold = token_threshold_k * 1000 if token_threshold_k else None
    token_count = count_tokens(
        file_io_to_text(upload.file), tokenizer, token_limit=token_threshold
    )
    upload.file.seek(0)
    if token_threshold is not None and token_count > token_threshold:
        results.rejected.append(
            RejectedFile(
                filename=filename,
                reason=f"Exceeds {token_threshold_k}K token limit",
            )
        )
        return
    results.accept(upload, token_count, skip_indexing=True)


def categorize_uploaded_files(
    files: list[UploadFile], db_session: Session
) -> CategorizedFiles:
    """
    Categorize uploaded files based on text extractability and tokenized length.

    - Images are estimated for token cost via a patch-based heuristic.
    - Sandbox-only code files (.py, .js, .sh, …) must be text. They are
      accepted but flagged to skip indexing.
    - All other files are run through extract_file_text, which handles known
      document formats (.pdf, .docx, …) and falls back to a text-detection
      heuristic for unknown extensions.
    - Uses default tokenizer to compute token length.
    - If token length exceeds the admin-configured threshold, reject file.
    - If extension unsupported or text cannot be extracted, reject file.
    - A file with no name is rejected.
    - Otherwise marked as acceptable.
    """

    results = CategorizedFiles()
    default_model = fetch_default_model(db_session, LLMModelFlowType.CHAT)

    model_name = default_model.name if default_model else None
    provider_type = default_model.llm_provider.provider if default_model else None
    tokenizer = get_tokenizer(model_name=model_name, provider_type=provider_type)

    # Derive limits from admin-configurable settings.
    # For upload size: load_settings() resolves 0/None to a positive default.
    # For token threshold: 0 means "no limit" (converted to None below).
    settings = load_settings()
    max_upload_size_mb = (
        settings.user_file_max_upload_size_mb
    )  # always positive after load_settings()
    max_upload_size_bytes = (
        max_upload_size_mb * 1024 * 1024 if max_upload_size_mb else None
    )
    token_threshold_k = settings.file_token_count_threshold_k
    token_threshold = (
        token_threshold_k * 1000 if token_threshold_k else None
    )  # 0 → None = no limit

    # Running total of embedded images across PDFs in this batch. Once the
    # aggregate cap is reached, subsequent PDFs in the same upload are
    # rejected even if they'd individually fit under MAX_EMBEDDED_IMAGES_PER_FILE.
    batch_image_total = 0

    # Hoisted out of the loop to avoid a KV-store lookup per file.
    image_extraction_enabled = get_image_extraction_and_analysis_enabled()

    for upload in files:
        try:
            # `upload_files` stores no file without a name.
            if not upload.filename:
                results.rejected.append(
                    RejectedFile(filename=UNKNOWN_FILENAME, reason="File has no name")
                )
                continue
            filename = upload.filename

            # Size limit is a hard safety cap.
            if max_upload_size_bytes is not None and is_upload_too_large(
                upload, max_upload_size_bytes
            ):
                results.rejected.append(
                    RejectedFile(
                        filename=filename,
                        reason=f"Exceeds {max_upload_size_mb} MB file size limit",
                    )
                )
                continue

            extension = get_file_ext(filename)

            # If image, estimate tokens via dedicated method first
            if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
                try:
                    token_count = estimate_image_tokens_for_upload(upload)
                except (UnidentifiedImageError, OSError) as e:
                    logger.warning(
                        "Failed to process image file '%s': %s", filename, str(e)
                    )
                    results.rejected.append(
                        RejectedFile(
                            filename=filename, reason="Unsupported file contents"
                        )
                    )
                    continue

                if token_threshold is not None and token_count > token_threshold:
                    results.rejected.append(
                        RejectedFile(
                            filename=filename,
                            reason=f"Exceeds {token_threshold_k}K token limit",
                        )
                    )
                else:
                    results.accept(upload, token_count)
                continue

            # Code and script files: kept for the Python tool, never indexed.
            elif extension in OnyxFileExtensions.SANDBOX_ONLY_EXTENSIONS:
                _categorize_sandbox_only_file(
                    upload, filename, tokenizer, token_threshold_k, results
                )
                continue

            # Handle as text/document: attempt text extraction and count tokens.
            # Unknown extensions fall back to extract_file_text's text detection.
            else:
                if is_file_password_protected(
                    file=upload.file,
                    file_name=filename,
                    extension=extension,
                ):
                    logger.warning("%s is password protected", filename)
                    results.rejected.append(
                        RejectedFile(
                            filename=filename, reason="Document is password protected"
                        )
                    )
                    continue

                # Reject documents with an unreasonable number of embedded
                # images (either per-file or accumulated across this upload
                # batch). A file with thousands of embedded images can OOM the
                # user-file-processing celery worker because every image is
                # decoded with PIL and then sent to the vision LLM. With image
                # extraction off, no image is ever decoded, so the caps (and
                # the cost of counting) do not apply.
                count: int = 0
                image_bearing_ext = extension in (".pdf", ".docx")
                if image_bearing_ext and image_extraction_enabled:
                    file_cap = MAX_EMBEDDED_IMAGES_PER_FILE
                    batch_cap = MAX_EMBEDDED_IMAGES_PER_UPLOAD
                    # Use the larger of the two caps as the short-circuit
                    # threshold so we get a useful count for both checks.
                    # These helpers restore the stream position.
                    counter = (
                        count_pdf_embedded_images
                        if extension == ".pdf"
                        else count_docx_embedded_images
                    )
                    count = counter(upload.file, max(file_cap, batch_cap))
                    if count > file_cap:
                        results.rejected.append(
                            RejectedFile(
                                filename=filename,
                                reason=(
                                    f"Document contains too many embedded "
                                    f"images (more than {file_cap}). Try "
                                    f"splitting it into smaller files."
                                ),
                            )
                        )
                        continue
                    if batch_image_total + count > batch_cap:
                        results.rejected.append(
                            RejectedFile(
                                filename=filename,
                                reason=(
                                    f"Upload would exceed the "
                                    f"{batch_cap}-image limit across all "
                                    f"files in this batch. Try uploading "
                                    f"fewer image-heavy files at once."
                                ),
                            )
                        )
                        continue
                    batch_image_total += count

                text_content = extract_file_text(
                    file=upload.file,
                    file_name=filename,
                    break_on_unprocessable=False,
                    extension=extension,
                )
                if not text_content:
                    # Documents with embedded images (e.g. scans) have no
                    # extractable text but can still be indexed via the
                    # vision-LLM captioning path. `count` is only populated
                    # when image extraction is enabled.
                    if image_bearing_ext and count > 0:
                        results.accept(upload, 0)
                        try:
                            upload.file.seek(0)
                        except Exception as e:
                            logger.warning(
                                "Failed to reset file pointer for '%s': %s",
                                filename,
                                str(e),
                            )
                        continue

                    logger.warning("No text content extracted from '%s'", filename)
                    if image_bearing_ext and not image_extraction_enabled:
                        reason = (
                            "No text could be extracted, and image processing "
                            "is disabled by an admin"
                        )
                    else:
                        reason = f"Unsupported file type: {extension}"
                    results.rejected.append(
                        RejectedFile(filename=filename, reason=reason)
                    )
                    continue

                token_count = count_tokens(
                    text_content, tokenizer, token_limit=token_threshold
                )
                exceeds_threshold = (
                    token_threshold is not None and token_count > token_threshold
                )
                if exceeds_threshold and _skip_token_threshold(extension):
                    # Exempt extensions (e.g. spreadsheets) are accepted
                    # but flagged to skip indexing — only metadata is
                    # injected into the LLM context.
                    results.accept(upload, token_count, skip_indexing=True)
                elif exceeds_threshold:
                    results.rejected.append(
                        RejectedFile(
                            filename=filename,
                            reason=f"Exceeds {token_threshold_k}K token limit",
                        )
                    )
                else:
                    results.accept(upload, token_count)

                # Reset file pointer for subsequent upload handling
                try:
                    upload.file.seek(0)
                except Exception as e:
                    logger.warning(
                        "Failed to reset file pointer for '%s': %s", filename, str(e)
                    )
        except Exception as e:
            logger.warning(
                "Failed to process uploaded file '%s' (error_type=%s, error=%s)",
                get_safe_filename(upload),
                type(e).__name__,
                str(e),
            )
            results.rejected.append(
                RejectedFile(
                    filename=get_safe_filename(upload),
                    reason="Failed to process upload",
                )
            )

    return results
