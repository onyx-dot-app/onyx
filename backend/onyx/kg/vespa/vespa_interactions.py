import json
from collections.abc import Generator

from onyx.configs.constants import OnyxCallTypes
from onyx.db.kg_config import KGConfigSettings
from onyx.document_index.vespa.chunk_retrieval import _get_chunks_via_visit_api
from onyx.document_index.vespa.chunk_retrieval import VespaChunkRequest
from onyx.document_index.vespa.index import IndexFilters
from onyx.kg.models import KGChunkFormat
from onyx.kg.models import KGClassificationContent
from onyx.kg.utils.formatting_utils import kg_email_processing
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_document_classification_content_for_kg_processing(
    document_ids: list[str],
    source: str,
    index_name: str,
    kg_config_settings: KGConfigSettings,
    batch_size: int = 8,
    num_classification_chunks: int = 3,
    entity_type: str | None = None,
) -> Generator[list[KGClassificationContent], None, None]:
    """
    Generates the content used for initial classification of a document from
    the first num_classification_chunks chunks.
    """

    classification_content_list: list[KGClassificationContent] = []

    for i in range(0, len(document_ids), batch_size):
        batch_document_ids = document_ids[i : i + batch_size]
        for document_id in batch_document_ids:
            # ... existing code for getting chunks and processing ...
            first_num_classification_chunks: list[dict] = _get_chunks_via_visit_api(
                chunk_request=VespaChunkRequest(
                    document_id=document_id,
                    max_chunk_ind=num_classification_chunks - 1,
                    min_chunk_ind=0,
                ),
                index_name=index_name,
                filters=IndexFilters(access_control_list=None),
                field_names=[
                    "document_id",
                    "chunk_id",
                    "title",
                    "content",
                    "metadata",
                    "source_type",
                    "primary_owners",
                    "secondary_owners",
                ],
                get_large_chunks=False,
            )

            if len(first_num_classification_chunks) == 0:
                continue

            first_num_classification_chunks = sorted(
                first_num_classification_chunks, key=lambda x: x["fields"]["chunk_id"]
            )[:num_classification_chunks]

            classification_content = _get_classification_content_from_chunks(
                first_num_classification_chunks,
                kg_config_settings,
            )

            metadata = first_num_classification_chunks[0]["fields"]["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            assert isinstance(metadata, dict) or metadata is None

            classification_content_list.append(
                KGClassificationContent(
                    document_id=document_id,
                    classification_content=classification_content,
                    source_type=first_num_classification_chunks[0]["fields"][
                        "source_type"
                    ],
                    source_metadata=metadata,
                    entity_type=entity_type,
                )
            )

        # Yield the batch of classification content
        if classification_content_list:
            yield classification_content_list
            classification_content_list = []

    # Yield any remaining items
    if classification_content_list:
        yield classification_content_list


def get_document_chunks_for_kg_processing(
    document_id: str,
    deep_extraction: bool,
    index_name: str,
    tenant_id: str,
    batch_size: int = 8,
) -> Generator[list[KGChunkFormat], None, None]:
    """
    Retrieves chunks from Vespa for the given document IDs and converts them to KGChunks.

    Args:
        document_id (str): ID of the document to fetch chunks for
        deep_extraction (bool): Whether to perform deep extraction
        index_name (str): Name of the Vespa index
        tenant_id (str): ID of the tenant
        batch_size (int): Number of chunks to fetch per batch

    Yields:
        list[KGChunk]: Batches of chunks ready for KG processing
    """

    current_batch: list[KGChunkFormat] = []

    # get all chunks for the document
    chunks = _get_chunks_via_visit_api(
        chunk_request=VespaChunkRequest(document_id=document_id),
        index_name=index_name,
        filters=IndexFilters(access_control_list=None, tenant_id=tenant_id),
        field_names=[
            "document_id",
            "chunk_id",
            "title",
            "content",
            "metadata",
            "primary_owners",
            "secondary_owners",
            "source_type",
            "kg_entities",
            "kg_relationships",
            "kg_terms",
        ],
        get_large_chunks=False,
    )

    # Convert Vespa chunks to KGChunks
    # kg_chunks: list[KGChunkFormat] = []

    for i, chunk in enumerate(chunks):
        fields = chunk["fields"]
        if isinstance(fields.get("metadata", {}), str):
            fields["metadata"] = json.loads(fields["metadata"])
        current_batch.append(
            KGChunkFormat(
                connector_id=None,  # We may need to adjust this
                document_id=fields.get("document_id"),
                chunk_id=fields.get("chunk_id"),
                primary_owners=fields.get("primary_owners", []),
                secondary_owners=fields.get("secondary_owners", []),
                source_type=fields.get("source_type", ""),
                title=fields.get("title", ""),
                content=fields.get("content", ""),
                metadata=fields.get("metadata", {}),
                entities=fields.get("kg_entities", {}),
                relationships=fields.get("kg_relationships", {}),
                terms=fields.get("kg_terms", {}),
                deep_extraction=deep_extraction,
            )
        )

        if len(current_batch) >= batch_size:
            yield current_batch
            current_batch = []

    # Yield any remaining chunks
    if current_batch:
        yield current_batch


def _get_classification_content_from_call_chunks(
    first_num_classification_chunks: list[dict],
    kg_config_settings: KGConfigSettings,
) -> str:
    """
    Creates a KGClassificationContent object from a list of call chunks.
    """

    assert isinstance(kg_config_settings.KG_IGNORE_EMAIL_DOMAINS, list)

    primary_owners = first_num_classification_chunks[0]["fields"].get(
        "primary_owners", []
    )
    secondary_owners = first_num_classification_chunks[0]["fields"].get(
        "secondary_owners", []
    )

    company_participant_emails = set()
    account_participant_emails = set()

    for owner in primary_owners + secondary_owners:
        kg_owner = kg_email_processing(owner, kg_config_settings)
        if any(
            domain.lower() in kg_owner.company.lower()
            for domain in kg_config_settings.KG_IGNORE_EMAIL_DOMAINS
        ):
            continue

        if kg_owner.employee:
            company_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")
        else:
            account_participant_emails.add(f"{kg_owner.name} -- ({kg_owner.company})")

    participant_string = "\n  - " + "\n  - ".join(company_participant_emails)
    account_participant_string = "\n  - " + "\n  - ".join(account_participant_emails)

    title_string = first_num_classification_chunks[0]["fields"]["title"]
    content_string = "\n".join(
        [
            chunk_content["fields"]["content"]
            for chunk_content in first_num_classification_chunks
        ]
    )

    classification_content = f"{title_string}\n\nVendor Participants:\n{participant_string}\n\n\
Other Participants:\n{account_participant_string}\n\nBeginning of Call:\n{content_string}"

    return classification_content


def _get_classification_content_from_chunks(
    first_num_classification_chunks: list[dict],
    kg_config_settings: KGConfigSettings,
) -> str:
    """
    Creates a KGClassificationContent object from a list of chunks.
    """

    source_type = first_num_classification_chunks[0]["fields"]["source_type"]

    if source_type.lower() in [call_type.value.lower() for call_type in OnyxCallTypes]:
        classification_content = _get_classification_content_from_call_chunks(
            first_num_classification_chunks,
            kg_config_settings,
        )

    else:
        classification_content = (
            first_num_classification_chunks[0]["fields"]["title"]
            + "\n"
            + "\n".join(
                [
                    chunk_content["fields"]["content"]
                    for chunk_content in first_num_classification_chunks
                ]
            )
        )

    return classification_content
