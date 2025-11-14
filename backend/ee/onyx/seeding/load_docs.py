
import json
import os
from typing import List

from cohere import Client

from ee.onyx.configs.app_configs import COHERE_DEFAULT_API_KEY

Embedding = List[float]


def _resolve_documents_path(seeding_dir: str, use_cohere: bool) -> str:
    """Определяет путь к файлу документов в зависимости от режима."""
    if use_cohere:
        return os.path.join(seeding_dir, "initial_docs_cohere.json")
    return os.path.join(seeding_dir, "initial_docs.json")


def _embed_document_section(
    embedding_client: Client, text: str, model_variant: str
) -> Embedding:
    """Выполняет эмбеддинг для раздела документа."""
    response = embedding_client.embed(
        texts=[text],
        model=model_variant,
        input_type="search_document",
    )
    return response.embeddings[0]


def load_processed_docs(cohere_enabled: bool) -> list[dict]:
    """
    Загружает и обрабатывает начальные документы.
    При активации Cohere добавляет эмбеддинги заголовков и содержимого.
    """
    current_dir = os.getcwd()
    seeding_root = os.path.join(current_dir, "onyx", "seeding")
    target_path = _resolve_documents_path(seeding_root, cohere_enabled)

    with open(target_path, "r", encoding="utf-8") as file_handle:
        loaded_data: list[dict] = json.load(file_handle)

    if cohere_enabled and COHERE_DEFAULT_API_KEY:
        embedding_service = Client(api_key=COHERE_DEFAULT_API_KEY)
        embedding_type = "embed-english-v3.0"

        doc_count = len(loaded_data)
        index = 0
        while index < doc_count:
            current_doc = loaded_data[index]
            doc_title = current_doc["title"]
            doc_content = current_doc["content"]

            title_vec = _embed_document_section(
                embedding_service, doc_title, embedding_type
            )
            content_vec = _embed_document_section(
                embedding_service, doc_content, embedding_type
            )

            current_doc["title_embedding"] = title_vec
            current_doc["content_embedding"] = content_vec
            index += 1

    return loaded_data
