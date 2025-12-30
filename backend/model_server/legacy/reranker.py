# import asyncio
# from typing import Optional
# from typing import TYPE_CHECKING

# from fastapi import APIRouter
# from fastapi import HTTPException

# from model_server.utils import simple_log_function_time
# from onyx.utils.logger import setup_logger
# from shared_configs.configs import INDEXING_ONLY
# from shared_configs.model_server_models import RerankRequest
# from shared_configs.model_server_models import RerankResponse

# if TYPE_CHECKING:
#     from sentence_transformers import CrossEncoder

# logger = setup_logger()

# router = APIRouter(prefix="/encoder")

# _RERANK_MODEL: Optional["CrossEncoder"] = None


# def get_local_reranking_model(
#     model_name: str,
# ) -> "CrossEncoder":
#     global _RERANK_MODEL
#     from sentence_transformers import CrossEncoder

#     if _RERANK_MODEL is None:
#         logger.notice(f"Loading {model_name}")
#         model = CrossEncoder(model_name)
#         _RERANK_MODEL = model
#     return _RERANK_MODEL


# @simple_log_function_time()
# async def local_rerank(query: str, docs: list[str], model_name: str) -> list[float]:
#     cross_encoder = get_local_reranking_model(model_name)
#     # Run CPU-bound reranking in a thread pool
#     return await asyncio.get_event_loop().run_in_executor(
#         None,
#         lambda: cross_encoder.predict([(query, doc) for doc in docs]).tolist(),
#     )


# @router.post("/cross-encoder-scores")
# async def process_rerank_request(rerank_request: RerankRequest) -> RerankResponse:
#     """Cross encoders can be purely black box from the app perspective"""
#     # Only local models should use this endpoint - API providers should make direct API calls
#     if rerank_request.provider_type is not None:
#         raise ValueError(
#             f"Model server reranking endpoint should only be used for local models. "
#             f"API provider '{rerank_request.provider_type}' should make direct API calls instead."
#         )

#     if INDEXING_ONLY:
#         raise RuntimeError("Indexing model server should not call reranking endpoint")

#     if not rerank_request.documents or not rerank_request.query:
#         raise HTTPException(
#             status_code=400, detail="Missing documents or query for reranking"
#         )
#     if not all(rerank_request.documents):
#         raise ValueError("Empty documents cannot be reranked.")

#     try:
#         # At this point, provider_type is None, so handle local reranking
#         sim_scores = await local_rerank(
#             query=rerank_request.query,
#             docs=rerank_request.documents,
#             model_name=rerank_request.model_name,
#         )
#         return RerankResponse(scores=sim_scores)

#     except Exception as e:
#         logger.exception(f"Error during reranking process:\n{str(e)}")
#         raise HTTPException(
#             status_code=500, detail="Failed to run Cross-Encoder reranking"
#         )
