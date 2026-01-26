"""
Persistent Document Writer for writing indexed documents to local filesystem or S3 with
hierarchical directory structure that mirrors the source organization.

Local mode (SandboxBackend.LOCAL):
    Writes to local filesystem at {PERSISTENT_DOCUMENT_STORAGE_PATH}/{tenant_id}/knowledge/{user_id}/...

Kubernetes mode (SandboxBackend.KUBERNETES):
    Writes to S3 at s3://{SANDBOX_S3_BUCKET}/{tenant_id}/knowledge/{user_id}/...
    This is the same location that kubernetes_sandbox_manager.py reads from when
    provisioning sandboxes.

Both modes use consistent tenant/user-segregated paths for multi-tenant isolation.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client

from onyx.connectors.models import Document
from onyx.server.features.build.configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_S3_BUCKET
from onyx.server.features.build.configs import SandboxBackend
from onyx.utils.logger import setup_logger

logger = setup_logger()


# =============================================================================
# Shared Utilities for Path Building
# =============================================================================


def sanitize_path_component(component: str, replace_slash: bool = True) -> str:
    """Sanitize a path component for file system / S3 key safety.

    Args:
        component: The path component to sanitize
        replace_slash: If True, replaces forward slashes (needed for local filesystem).
                      Set to False for S3 where `/` is a valid delimiter.

    Returns:
        Sanitized path component safe for use in file paths or S3 keys
    """
    # Replace spaces with underscores
    sanitized = component.replace(" ", "_")
    # Replace problematic characters
    if replace_slash:
        sanitized = sanitized.replace("/", "_")
    sanitized = sanitized.replace("\\", "_").replace(":", "_")
    sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
    sanitized = sanitized.replace('"', "_").replace("?", "_").replace("*", "_")
    # Also handle null bytes and other control characters
    sanitized = "".join(c for c in sanitized if ord(c) >= 32)
    return sanitized.strip() or "unnamed"


def sanitize_filename(name: str, replace_slash: bool = True) -> str:
    """Sanitize name for use as filename.

    Args:
        name: The filename to sanitize
        replace_slash: Passed through to sanitize_path_component

    Returns:
        Sanitized filename, truncated with hash suffix if too long
    """
    sanitized = sanitize_path_component(name, replace_slash=replace_slash)
    if len(sanitized) > 200:
        # Keep first 150 chars + hash suffix for uniqueness
        hash_suffix = hashlib.sha256(name.encode()).hexdigest()[:16]
        return f"{sanitized[:150]}_{hash_suffix}"
    return sanitized


def get_base_filename(doc: Document, replace_slash: bool = True) -> str:
    """Get base filename from document, preferring semantic identifier.

    Args:
        doc: The document to get filename for
        replace_slash: Passed through to sanitize_filename

    Returns:
        Sanitized base filename (without extension)
    """
    name = doc.semantic_identifier or doc.title or doc.id
    return sanitize_filename(name, replace_slash=replace_slash)


def build_document_subpath(doc: Document, replace_slash: bool = True) -> list[str]:
    """Build the source/hierarchy path components from a document.

    Returns path components like: [source, hierarchy_part1, hierarchy_part2, ...]

    This is the common part of the path that comes after user/tenant segregation.

    Args:
        doc: The document to build path for
        replace_slash: Passed through to sanitize_path_component

    Returns:
        List of sanitized path components
    """
    parts: list[str] = []

    # Source type (e.g., "google_drive", "confluence")
    parts.append(doc.source.value)

    # Get hierarchy from doc_metadata
    hierarchy = doc.doc_metadata.get("hierarchy", {}) if doc.doc_metadata else {}
    source_path = hierarchy.get("source_path", [])

    if source_path:
        parts.extend(
            [
                sanitize_path_component(p, replace_slash=replace_slash)
                for p in source_path
            ]
        )

    return parts


def resolve_duplicate_filename(
    doc: Document,
    base_filename: str,
    has_duplicates: bool,
    replace_slash: bool = True,
) -> str:
    """Resolve filename, appending ID suffix if there are duplicates.

    Args:
        doc: The document (for ID extraction)
        base_filename: The base filename without extension
        has_duplicates: Whether there are other docs with the same base filename
        replace_slash: Passed through to sanitize_path_component

    Returns:
        Final filename with .json extension
    """
    if has_duplicates:
        id_suffix = sanitize_path_component(doc.id, replace_slash=replace_slash)
        if len(id_suffix) > 50:
            id_suffix = hashlib.sha256(doc.id.encode()).hexdigest()[:16]
        return f"{base_filename}_{id_suffix}.json"
    return f"{base_filename}.json"


def serialize_document(doc: Document) -> dict[str, Any]:
    """Serialize a document to a dictionary for JSON storage.

    Args:
        doc: The document to serialize

    Returns:
        Dictionary representation of the document
    """
    return {
        "id": doc.id,
        "semantic_identifier": doc.semantic_identifier,
        "title": doc.title,
        "source": doc.source.value,
        "doc_updated_at": (
            doc.doc_updated_at.isoformat() if doc.doc_updated_at else None
        ),
        "metadata": doc.metadata,
        "doc_metadata": doc.doc_metadata,
        "sections": [
            {"text": s.text if hasattr(s, "text") else None, "link": s.link}
            for s in doc.sections
        ],
        "primary_owners": [o.model_dump() for o in (doc.primary_owners or [])],
        "secondary_owners": [o.model_dump() for o in (doc.secondary_owners or [])],
    }


# =============================================================================
# Classes
# =============================================================================


class PersistentDocumentWriter:
    """Writes indexed documents to local filesystem with hierarchical structure.

    Documents are stored in tenant/user-segregated paths:
    {base_path}/{tenant_id}/knowledge/{user_id}/{source}/{hierarchy}/document.json

    This enables per-tenant and per-user isolation for sandbox access control.
    """

    def __init__(
        self,
        base_path: str,
        tenant_id: str,
        user_id: str,
    ):
        self.base_path = Path(base_path)
        self.tenant_id = tenant_id
        self.user_id = user_id

    def write_documents(self, documents: list[Document]) -> list[str]:
        """Write documents to local filesystem, returns written file paths."""
        written_paths: list[str] = []

        # Build a map of base filenames to detect duplicates
        # Key: (directory_path, base_filename) -> list of docs with that name
        filename_map: dict[tuple[Path, str], list[Document]] = {}

        for doc in documents:
            dir_path = self._build_directory_path(doc)
            base_filename = get_base_filename(doc, replace_slash=True)
            key = (dir_path, base_filename)
            if key not in filename_map:
                filename_map[key] = []
            filename_map[key].append(doc)

        # Now write documents, appending ID if there are duplicates
        for (dir_path, base_filename), docs in filename_map.items():
            has_duplicates = len(docs) > 1
            for doc in docs:
                filename = resolve_duplicate_filename(
                    doc, base_filename, has_duplicates, replace_slash=True
                )
                path = dir_path / filename
                self._write_document(doc, path)
                written_paths.append(str(path))

        return written_paths

    def _build_directory_path(self, doc: Document) -> Path:
        """Build directory path from document metadata.

        Documents are stored under tenant/user-segregated paths:
        {base_path}/{tenant_id}/knowledge/{user_id}/{source}/{hierarchy}/

        This enables per-tenant and per-user isolation for sandbox access control.
        """
        # Tenant and user segregation prefix (matches S3 path structure)
        parts = [self.tenant_id, "knowledge", self.user_id]
        # Add source and hierarchy from document
        parts.extend(build_document_subpath(doc, replace_slash=True))

        return self.base_path / "/".join(parts)

    def _write_document(self, doc: Document, path: Path) -> None:
        """Serialize and write document to filesystem."""
        content = serialize_document(doc)

        # Create parent directories if they don't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the JSON file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, default=str)

        logger.debug(f"Wrote document to {path}")


class S3PersistentDocumentWriter:
    """Writes indexed documents to S3 with hierarchical structure.

    Documents are stored in tenant/user-segregated paths:
    s3://{bucket}/{tenant_id}/knowledge/{user_id}/{source}/{hierarchy}/document.json

    This matches the location that KubernetesSandboxManager reads from when
    provisioning sandboxes (via the init container's aws s3 sync command).
    """

    def __init__(self, tenant_id: str, user_id: str):
        """Initialize S3PersistentDocumentWriter.

        Args:
            tenant_id: Tenant identifier for multi-tenant isolation
            user_id: User ID for user-segregated storage paths
        """
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.bucket = SANDBOX_S3_BUCKET
        self._s3_client: S3Client | None = None

    def _get_s3_client(self) -> S3Client:
        """Lazily initialize S3 client.

        Uses the default boto3 credential chain which supports:
        - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        - AWS config files
        - IAM roles (EC2/ECS/EKS instance profiles, IRSA)
        """
        if self._s3_client is None:
            self._s3_client = boto3.client("s3")
        return self._s3_client

    def write_documents(self, documents: list[Document]) -> list[str]:
        """Write documents to S3, returns written S3 keys.

        Args:
            documents: List of documents to write

        Returns:
            List of S3 keys that were written
        """
        written_keys: list[str] = []

        # Build a map of base keys to detect duplicates
        # Key: (directory_prefix, base_filename) -> list of docs with that name
        key_map: dict[tuple[str, str], list[Document]] = {}

        for doc in documents:
            dir_prefix = self._build_directory_path(doc)
            base_filename = get_base_filename(doc, replace_slash=False)
            key = (dir_prefix, base_filename)
            if key not in key_map:
                key_map[key] = []
            key_map[key].append(doc)

        # Now write documents, appending ID if there are duplicates
        s3_client = self._get_s3_client()

        for (dir_prefix, base_filename), docs in key_map.items():
            has_duplicates = len(docs) > 1
            for doc in docs:
                filename = resolve_duplicate_filename(
                    doc, base_filename, has_duplicates, replace_slash=False
                )
                s3_key = f"{dir_prefix}/{filename}"
                self._write_document(s3_client, doc, s3_key)
                written_keys.append(s3_key)

        return written_keys

    def _build_directory_path(self, doc: Document) -> str:
        """Build S3 key prefix from document metadata.

        Documents are stored under tenant/user-segregated paths:
        {tenant_id}/knowledge/{user_id}/{source}/{hierarchy}/

        This matches the path that KubernetesSandboxManager syncs from:
        aws s3 sync "s3://{bucket}/{tenant_id}/knowledge/{user_id}/" /workspace/files/
        """
        # Tenant and user segregation (matches K8s sandbox init container path)
        parts = [self.tenant_id, "knowledge", self.user_id]
        # Add source and hierarchy from document
        parts.extend(build_document_subpath(doc, replace_slash=False))

        return "/".join(parts)

    def _write_document(self, s3_client: S3Client, doc: Document, s3_key: str) -> None:
        """Serialize and write document to S3."""
        content = serialize_document(doc)
        json_content = json.dumps(content, indent=2, default=str)

        try:
            s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json_content.encode("utf-8"),
                ContentType="application/json",
            )
            logger.debug(f"Wrote document to s3://{self.bucket}/{s3_key}")
        except ClientError as e:
            logger.error(f"Failed to write to S3: {e}")
            raise


def get_persistent_document_writer(
    user_id: str,
    tenant_id: str,
) -> PersistentDocumentWriter | S3PersistentDocumentWriter:
    """Factory function to create a PersistentDocumentWriter with default configuration.

    Args:
        user_id: User ID for user-segregated storage paths.
        tenant_id: Tenant ID for multi-tenant isolation.

    Both local and S3 modes use consistent tenant/user-segregated paths:
        - Local: {base_path}/{tenant_id}/knowledge/{user_id}/...
        - S3: s3://{bucket}/{tenant_id}/knowledge/{user_id}/...

    Returns:
        PersistentDocumentWriter for local mode, S3PersistentDocumentWriter for K8s mode
    """
    if SANDBOX_BACKEND == SandboxBackend.LOCAL:
        return PersistentDocumentWriter(
            base_path=PERSISTENT_DOCUMENT_STORAGE_PATH,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    elif SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
        return S3PersistentDocumentWriter(
            tenant_id=tenant_id,
            user_id=user_id,
        )
    else:
        raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")
