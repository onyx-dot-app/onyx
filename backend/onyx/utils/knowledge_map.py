import json
from typing import Callable, TYPE_CHECKING

import requests
from sqlalchemy.orm import Session

from onyx.chat.models import LlmDoc
from onyx.configs.app_configs import LANGFLOW_BASE_URL, LANGFLOW_API_KEY
from onyx.context.search.models import InferenceSection, IndexFilters, InferenceChunk
from onyx.context.search.postprocessing.postprocessing import cleanup_chunks
from onyx.context.search.retrieval.search_runner import combine_inference_chunks
from onyx.context.search.utils import inference_section_from_chunks
from onyx.db.document import get_documents_by_cc_pair
from onyx.db.document_set import get_document_set_by_id
from onyx.db.knowledge_map import upsert_knowledge_map_answer
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.document_index.interfaces import DocumentIndex, VespaChunkRequest
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

if TYPE_CHECKING:
    from onyx.db.models import KnowledgeMap

logger = setup_logger()


def inference_sections_from_ids(
    doc_identifiers: list[str],
    document_index: DocumentIndex,
) -> list[InferenceSection]:
    # Currently only fetches whole docs
    doc_ids_set = set(doc_id for doc_id in doc_identifiers)

    chunk_requests: list[VespaChunkRequest] = [
        VespaChunkRequest(document_id=doc_id) for doc_id in doc_ids_set
    ]

    # No need for ACL here because the doc ids were validated beforehand
    filters = IndexFilters(access_control_list=None)

    retrieved_chunks = document_index.id_based_retrieval(
        chunk_requests=chunk_requests,
        filters=filters,
    )

    cleaned_chunks = cleanup_chunks(retrieved_chunks)
    if not cleaned_chunks:
        return []

    # Group chunks by document ID
    chunks_by_doc_id: dict[str, list[InferenceChunk]] = {}
    for chunk in cleaned_chunks:
        chunks_by_doc_id.setdefault(chunk.document_id, []).append(chunk)

    inference_sections = [
        section
        for chunks in chunks_by_doc_id.values()
        if chunks
        and (
            section := inference_section_from_chunks(
                # The scores will always be 0 because the fetching by id gives back
                # no search scores. This is not needed though if the user is explicitly
                # selecting a document.
                center_chunk=chunks[0],
                chunks=chunks,
            )
        )
    ]

    return inference_sections


def get_knowledge_map_answer_by_document(document_text: str, pipeline_id: str) -> dict:
    """
    Функция для получения ответов от Flowise в виде:

    {
       "тема": "ответ"
    }
    """
    request = requests.post(
        LANGFLOW_BASE_URL + f"/api/v1/run/{pipeline_id}",
        json={"input_value": document_text},
        headers={"x-api-key": LANGFLOW_API_KEY,
                 "Content-Type": "application/json"},
    )
    response = request.json()

    return response


def get_knowledge_map_answers_by_document_list(session: Session, knowledge_map: "KnowledgeMap") -> dict:
    """
    Функция на уровень выше которая получает список документов по document_set_id, далее читает их и отправляет в функцию
    для работы с Flowise.
    """
    document_list_from_db = get_document_set_by_id(
        db_session=session, document_set_id=knowledge_map.document_set_id
    )
    document_list = []
    for doc in document_list_from_db.connector_credential_pairs:
        if doc.connector.source == "FILE":
            file_locations = doc.connector.connector_specific_config.get('file_locations')
            if file_locations:
                document_list.append("FILE_CONNECTOR__" + file_locations[0])
        else:
            documents_from_connector = get_documents_by_cc_pair(doc.id, session)
            for doc_from_cc in documents_from_connector:
                document_list.append(doc_from_cc.id)

    document_index = get_current_primary_default_document_index(session)
    selected_llm_docs = inference_sections_from_ids(
        doc_identifiers=document_list,
        document_index=document_index,
    )

    answers = {}
    for doc in selected_llm_docs:
        result = get_knowledge_map_answer_by_document(doc.combined_content, knowledge_map.flowise_pipeline_id)
        answers[doc.center_chunk.document_id] = []
        for item in json.loads(result['outputs'][0]['outputs'][0]['results']['message']['text'].strip("```").strip("json")).items():
            if item[1]:
                answers[doc.center_chunk.document_id].append({item[0]: item[1]})
                upsert_knowledge_map_answer(session, doc.center_chunk.document_id, knowledge_map.id, item[0], item[1])
    return answers
