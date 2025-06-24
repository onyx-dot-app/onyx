import json
from typing import Callable, TYPE_CHECKING

import requests
from sqlalchemy.orm import Session

from onyx.chat.models import LlmDoc
from onyx.configs.app_configs import FLOWISE_BASE_URL, FLOWISE_API_KEY
from onyx.context.search.retrieval.search_runner import combine_inference_chunks
from onyx.db.document import get_documents_by_cc_pair
from onyx.db.document_set import get_document_set_by_id
from onyx.db.knowledge_map import upsert_knowledge_map_answer
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

if TYPE_CHECKING:
    from onyx.db.models import KnowledgeMap

logger = setup_logger()


def inference_documents_from_ids(
        doc_identifiers: list[str],
        document_index: DocumentIndex,
) -> list[LlmDoc]:
    # Currently only fetches whole docs
    doc_ids_set = set(doc_id for doc_id in doc_identifiers)

    # No need for ACL here because the doc ids were validated beforehand
    functions_with_args: list[tuple[Callable, tuple]] = [
        (document_index.id_based_retrieval, (doc_id, None, None, None))
        for doc_id in doc_ids_set
    ]

    parallel_results = run_functions_tuples_in_parallel(
        functions_with_args, allow_failures=True
    )

    # Any failures to retrieve would give a None, drop the Nones and empty lists
    inference_chunks_sets = [res for res in parallel_results if res]

    return [combine_inference_chunks(chunk_set) for chunk_set in inference_chunks_sets]


def get_knowledge_map_answer_by_document(document_text: str, pipeline_id: str) -> dict:
    """
    Функция для получения ответов от Flowise в виде:

    {
       "тема": "ответ"
    }
    """
    request = requests.post(
        FLOWISE_BASE_URL + f"api/v1/prediction/{pipeline_id}",
        json={"question": document_text},
        headers={"Authorization": "Bearer " + FLOWISE_API_KEY},
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
    selected_llm_docs = inference_documents_from_ids(
        doc_identifiers=document_list,
        document_index=document_index,
    )

    answers = {}
    for doc in selected_llm_docs:
        result = get_knowledge_map_answer_by_document(doc.content, knowledge_map.flowise_pipeline_id)
        answers[doc.document_id] = []
        for item in json.loads(result['text'].strip("```").strip("json")).items():
            if item[1]:
                answers[doc.document_id].append({item[0]: item[1]})
                upsert_knowledge_map_answer(session, doc.document_id, knowledge_map.id, item[0], item[1])
    return answers
