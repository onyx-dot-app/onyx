# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# The NLP models used here are licensed under Apache 2.0, the original author's LICENSE file is
# included in this same directory.
# Specifically the sentence-transformers/all-distilroberta-v1 and cross-encoder/ms-marco-MiniLM-L-6-v2 models
# The original authors can be found at https://www.sbert.net/
import json

from danswer.chunking.models import InferenceChunk
from danswer.configs.app_configs import NUM_RETURNED_HITS
from danswer.configs.model_configs import CROSS_EMBED_CONTEXT_SIZE
from danswer.configs.model_configs import CROSS_ENCODER_MODEL
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.configs.model_configs import DOCUMENT_ENCODER_MODEL
from danswer.datastores.interfaces import Datastore
from danswer.datastores.interfaces import DatastoreFilter
from danswer.utils.logging import setup_logger
from danswer.utils.timing import log_function_time
from sentence_transformers import CrossEncoder  # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore


logger = setup_logger()


_EMBED_MODEL: None | SentenceTransformer = None
_RERANK_MODEL: None | CrossEncoder = None


def get_default_embedding_model() -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = SentenceTransformer(DOCUMENT_ENCODER_MODEL)
        _EMBED_MODEL.max_seq_length = DOC_EMBEDDING_CONTEXT_SIZE

    return _EMBED_MODEL


def get_default_reranking_model() -> CrossEncoder:
    global _RERANK_MODEL
    if _RERANK_MODEL is None:
        _RERANK_MODEL = CrossEncoder(CROSS_ENCODER_MODEL)
        _RERANK_MODEL.max_length = CROSS_EMBED_CONTEXT_SIZE

    return _RERANK_MODEL


def warm_up_models() -> None:
    get_default_embedding_model().encode("Danswer is so cool")
    get_default_reranking_model().predict(("What is Danswer", "Enterprise QA"))  # type: ignore


@log_function_time()
def semantic_reranking(
    query: str,
    chunks: list[InferenceChunk],
) -> list[InferenceChunk]:
    cross_encoder = get_default_reranking_model()
    sim_scores = cross_encoder.predict([(query, chunk.content) for chunk in chunks])  # type: ignore
    scored_results = list(zip(sim_scores, chunks))
    scored_results.sort(key=lambda x: x[0], reverse=True)
    ranked_sim_scores, ranked_chunks = zip(*scored_results)

    logger.debug(f"Reranked similarity scores: {str(ranked_sim_scores)}")

    return ranked_chunks


@log_function_time()
def retrieve_ranked_documents(
    query: str,
    filters: list[DatastoreFilter] | None,
    datastore: Datastore,
    num_hits: int = NUM_RETURNED_HITS,
) -> list[InferenceChunk] | None:
    top_chunks = datastore.semantic_retrieval(query, filters, num_hits)
    if not top_chunks:
        filters_log_msg = json.dumps(filters, separators=(",", ":")).replace("\n", "")
        logger.warning(
            f"Semantic search returned no results with filters: {filters_log_msg}"
        )
        return None
    ranked_chunks = semantic_reranking(query, top_chunks)

    top_docs = [ranked_chunk.source_links["0"] for ranked_chunk in ranked_chunks]
    files_log_msg = f"Top links from semantic search: {', '.join(top_docs)}"
    logger.info(files_log_msg)

    return ranked_chunks
