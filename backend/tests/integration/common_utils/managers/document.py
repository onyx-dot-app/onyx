from uuid import uuid4

import requests
from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentByConnectorCredentialPair
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.managers.api_key import DATestAPIKey
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import SimpleTestDocument
from tests.integration.common_utils.vespa import vespa_fixture


def _verify_document_permissions(
    retrieved_doc: dict,
    cc_pair: DATestCCPair,
    doc_creating_user: DATestUser,
    doc_set_names: list[str] | None = None,
    group_names: list[str] | None = None,
) -> None:
    acl_keys = set(retrieved_doc.get("access_control_list", {}).keys())

    if cc_pair.access_type == AccessType.PUBLIC:
        if "PUBLIC" not in acl_keys:
            raise ValueError(
                f"Document {retrieved_doc['document_id']} is public but does not have the PUBLIC ACL key"
            )

    if f"user_email:{doc_creating_user.email}" not in acl_keys:
        raise ValueError(
            f"Document {retrieved_doc['document_id']} was created by user"
            f" {doc_creating_user.email} but does not have the user_email:{doc_creating_user.email} ACL key"
        )

    if group_names is not None:
        expected_group_keys = {f"group:{group_name}" for group_name in group_names}
        found_group_keys = {key for key in acl_keys if key.startswith("group:")}
        if found_group_keys != expected_group_keys:
            raise ValueError(
                f"Document {retrieved_doc['document_id']} has incorrect group ACL keys. "
                f"Expected: {expected_group_keys}  Found: {found_group_keys}\n"
                f"All ACL keys: {acl_keys}"
            )

    if doc_set_names is not None:
        found_doc_set_names = set(retrieved_doc.get("document_sets", {}).keys())
        if found_doc_set_names != set(doc_set_names):
            raise ValueError(
                f"Document set names mismatch. \nFound: {found_doc_set_names}, \nExpected: {set(doc_set_names)}"
            )


def _build_ingestion_payload(
    document_id: str,
    cc_pair_id: int,
    content: str | None = None,
    metadata: dict | None = None,
) -> dict:
    text = content or f"This is test document {document_id}"
    doc_metadata: dict = {"document_id": document_id}
    if metadata:
        doc_metadata.update(metadata)

    return {
        "document": {
            "id": document_id,
            "sections": [{"text": text, "link": document_id}],
            "source": DocumentSource.NOT_APPLICABLE,
            "metadata": doc_metadata,
            "semantic_identifier": f"Test Document {document_id}",
            "from_ingestion_api": True,
        },
        "cc_pair_id": cc_pair_id,
    }


class DocumentIngestionManager:
    """Manager for ingesting test documents via the ingestion API."""

    @staticmethod
    def ingest(
        cc_pair: DATestCCPair,
        api_key: DATestAPIKey,
        content: str | None = None,
        document_id: str | None = None,
        metadata: dict | None = None,
    ) -> SimpleTestDocument:
        """Seed a single document via the ingestion API.

        The ingestion API indexes synchronously — the document is indexed
        and searchable by the time this method returns.
        """
        if document_id is None:
            document_id = f"test-doc-{uuid4()}"

        payload = _build_ingestion_payload(document_id, cc_pair.id, content, metadata)
        response = requests.post(
            f"{API_SERVER_URL}/onyx-api/ingestion",
            json=payload,
            headers=api_key.headers,
        )
        response.raise_for_status()

        return SimpleTestDocument(
            id=payload["document"]["id"],
            content=payload["document"]["sections"][0]["text"],
        )

    @staticmethod
    def ingest_multiple(
        cc_pair: DATestCCPair,
        api_key: DATestAPIKey,
        num_docs: int = NUM_DOCS,
        document_ids: list[str] | None = None,
    ) -> list[SimpleTestDocument]:
        """Seed multiple documents with auto-generated content."""
        if document_ids is None:
            document_ids = [f"test-doc-{uuid4()}" for _ in range(num_docs)]
        return [
            DocumentIngestionManager.ingest(
                cc_pair=cc_pair,
                api_key=api_key,
                document_id=doc_id,
            )
            for doc_id in document_ids
        ]

    @staticmethod
    def verify(
        vespa_client: vespa_fixture,
        cc_pair: DATestCCPair,
        doc_creating_user: DATestUser,
        doc_set_names: list[str] | None = None,
        group_names: list[str] | None = None,
        verify_deleted: bool = False,
    ) -> None:
        doc_ids = [document.id for document in cc_pair.documents]
        retrieved_docs_dict = vespa_client.get_documents_by_id(doc_ids)["documents"]

        retrieved_docs = {
            doc["fields"]["document_id"]: doc["fields"] for doc in retrieved_docs_dict
        }

        for document in cc_pair.documents:
            retrieved_doc = retrieved_docs.get(document.id)
            if not retrieved_doc:
                if not verify_deleted:
                    raise ValueError(f"Document not found: {document.id}")
                continue
            if verify_deleted:
                raise ValueError(
                    f"Document found when it should be deleted: {document.id}"
                )
            _verify_document_permissions(
                retrieved_doc,
                cc_pair,
                doc_creating_user,
                doc_set_names,
                group_names,
            )

    @staticmethod
    def fetch_documents_for_cc_pair(
        cc_pair_id: int,
        db_session: Session,
        vespa_client: vespa_fixture,
    ) -> list[SimpleTestDocument]:
        stmt = (
            select(DocumentByConnectorCredentialPair)
            .join(
                ConnectorCredentialPair,
                and_(
                    DocumentByConnectorCredentialPair.connector_id
                    == ConnectorCredentialPair.connector_id,
                    DocumentByConnectorCredentialPair.credential_id
                    == ConnectorCredentialPair.credential_id,
                ),
            )
            .where(ConnectorCredentialPair.id == cc_pair_id)
        )
        documents = db_session.execute(stmt).scalars().all()
        if not documents:
            return []

        doc_ids = [document.id for document in documents]
        retrieved_docs_dict = vespa_client.get_documents_by_id(doc_ids)["documents"]

        final_docs: list[SimpleTestDocument] = []
        for doc_dict in retrieved_docs_dict:
            doc_id = doc_dict["fields"]["document_id"]
            doc_content = doc_dict["fields"]["content"]
            image_file_id = doc_dict["fields"].get("image_file_name", None)
            final_docs.append(
                SimpleTestDocument(
                    id=doc_id, content=doc_content, image_file_id=image_file_id
                )
            )

        return final_docs

    @staticmethod
    def list_all(
        api_key: DATestAPIKey,
    ) -> list[dict]:
        """List all documents seeded via the ingestion API."""
        response = requests.get(
            f"{API_SERVER_URL}/onyx-api/ingestion",
            headers=api_key.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete(
        document_id: str,
        api_key: DATestAPIKey,
    ) -> None:
        response = requests.delete(
            f"{API_SERVER_URL}/onyx-api/ingestion/{document_id}",
            headers=api_key.headers,
        )
        response.raise_for_status()
