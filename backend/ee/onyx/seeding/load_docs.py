import json
import os
from typing import cast
from typing import List

from cohere import Client

from ee.onyx.configs.app_configs import COHERE_DEFAULT_API_KEY

Embedding = List[float]


def load_processed_docs(cohere_enabled: bool) -> list[dict]:
    base_path = os.path.join(os.getcwd(), "onyx", "seeding")

    if cohere_enabled and COHERE_DEFAULT_API_KEY:
        initial_docs_path = os.path.join(base_path, "initial_docs_cohere.json")
        processed_docs = json.load(open(initial_docs_path))

        cohere_client = Client(api_key=COHERE_DEFAULT_API_KEY)
        embed_model = "embed-english-v3.0"

        for doc in processed_docs:
            title_embed_response = cohere_client.embed(
                texts=[doc["title"]],
                model=embed_model,
                input_type="search_document",
            )
            content_embed_response = cohere_client.embed(
                texts=[doc["content"]],
                model=embed_model,
                input_type="search_document",
            )

            doc["title_embedding"] = cast(
                List[Embedding], title_embed_response.embeddings
            )[0]
            doc["content_embedding"] = cast(
                List[Embedding], content_embed_response.embeddings
            )[0]
    else:
        initial_docs_path = os.path.join(base_path, "initial_docs.json")
        processed_docs = json.load(open(initial_docs_path))

    return processed_docs
