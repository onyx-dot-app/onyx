import os

# Feature flag for enabling proposal review
ENABLE_PROPOSAL_REVIEW = (
    os.environ.get("ENABLE_PROPOSAL_REVIEW", "true").lower() == "true"
)

# Maximum file size for checklist imports (in MB)
IMPORT_MAX_FILE_SIZE_MB = int(
    os.environ.get("PROPOSAL_REVIEW_IMPORT_MAX_FILE_SIZE_MB", "50")
)
IMPORT_MAX_FILE_SIZE_BYTES = IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024

# Maximum file size for document uploads (in MB)
DOCUMENT_UPLOAD_MAX_FILE_SIZE_MB = int(
    os.environ.get("PROPOSAL_REVIEW_DOCUMENT_UPLOAD_MAX_FILE_SIZE_MB", "100")
)
DOCUMENT_UPLOAD_MAX_FILE_SIZE_BYTES = DOCUMENT_UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024
