import hashlib
from functools import lru_cache
from typing import Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from onyx.auth.users import current_user
from onyx.configs.app_configs import KROKI_ENABLED
from onyx.configs.app_configs import KROKI_URL
from onyx.configs.app_configs import KROKI_MAX_LLM_RETRIES, KROKI_CORRECTION_MODEL_NAME
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from typing import Optional # Added for type hinting

from onyx.llm.factory import get_default_llms
from onyx.llm.exceptions import GenAIDisabledException
from onyx.llm.chat_llm import LLMTimeoutError, LLMRateLimitError
from onyx.llm.interfaces import LLM # For type hinting
from onyx.db.engine import get_session_context_manager
from onyx.db.llm import fetch_default_provider
from onyx.llm.factory import llm_from_provider

logger = setup_logger("onyx.kroki")

router = APIRouter(prefix="/kroki", dependencies=[Depends(current_user)])

class DiagramRequest(BaseModel):
    content: str

# Supported diagram types by Kroki
SUPPORTED_DIAGRAM_TYPES = {
    "blockdiag", "seqdiag", "actdiag", "nwdiag", "packetdiag", "rackdiag",
    "graphviz", "pikchr", "erd", "excalidraw", "vega", "vegalite", 
    "ditaa", "mermaid", "nomnoml", "plantuml", "bpmn", "bytefield",
    "wavedrom", "svgbob", "c4plantuml", "structurizr", "umlet", 
    "wireviz", "symbolator"
}

@lru_cache(maxsize=128)
def _cached_kroki_request(diagram_type: str, content_hash: str, initial_content: str) -> Dict[str, Any]:
    """
    Cached function to make requests to Kroki service.
    Uses content hash as part of cache key to ensure same content returns cached result.
    Implements a retry mechanism with LLM-based correction for syntax errors.
    """
    if not KROKI_URL:
        # This check is outside the loop as it's a fundamental configuration issue.
        raise HTTPException(status_code=503, detail="Kroki service not configured")

    current_content = initial_content
    
    # Loop for initial attempt + KROKI_MAX_LLM_RETRIES
    # Total attempts = 1 (initial) + KROKI_MAX_LLM_RETRIES
    for attempt_number in range(1 + KROKI_MAX_LLM_RETRIES):
        is_retry_attempt = attempt_number > 0

        log_message_prefix = f"Kroki request attempt {attempt_number + 1}/{1 + KROKI_MAX_LLM_RETRIES}"
        if is_retry_attempt:
            log_message_prefix += " (LLM Retry)"
        
        try:
            # Make request to Kroki service
            with httpx.Client(timeout=30.0) as client:
                logger.debug(
                    f"{log_message_prefix}: Sending to Kroki for diagram type '{diagram_type}'. "
                    f"Original content hash: {content_hash}. "
                    f"Current content snippet:\n{current_content}"
                )
                response = client.post(
                    f"{KROKI_URL}/{diagram_type}/svg",
                    content=current_content,  # Use current_content, which might be LLM corrected
                    headers={"Content-Type": "text/plain"}
                )
            
            if response.status_code == 200:
                logger.info(
                    f"{log_message_prefix}: Kroki request successful for '{diagram_type}', "
                    f"original hash: {content_hash}."
                )
                return {"svg": response.text}
            
            elif response.status_code == 400:
                # Syntax error in diagram
                kroki_error_message = response.text or "Invalid diagram syntax"
                logger.warning(
                    f"{log_message_prefix}: Kroki returned 400 (Syntax Error) for '{diagram_type}', "
                    f"original hash: {content_hash}. Error: {kroki_error_message}"
                )

                # Check if more retries are allowed (i.e., if current attempt_number is less than KROKI_MAX_LLM_RETRIES)
                # attempt_number is 0-indexed for retries (0 means initial attempt, 1 means first retry, etc.)
                if attempt_number < KROKI_MAX_LLM_RETRIES:
                    logger.info(
                        f"Attempting LLM correction for '{diagram_type}' "
                        f"(Retry attempt {attempt_number + 1} of {KROKI_MAX_LLM_RETRIES} allowed retries)."
                    )
                    
                    # --- BEGIN LLM CORRECTION IMPLEMENTATION ---
                    corrected_code_from_llm: Optional[str] = None
                    try:
                        # LLM instance for correction, potentially specialized
                        correction_llm_instance: Optional[LLM] = None

                        # Try to get the specific correction model
                        if KROKI_CORRECTION_MODEL_NAME:
                            try:
                                with get_session_context_manager() as db_session:
                                    default_llm_provider_details = fetch_default_provider(db_session)

                                if default_llm_provider_details:
                                    correction_llm_instance = llm_from_provider(
                                        KROKI_CORRECTION_MODEL_NAME,
                                        default_llm_provider_details,
                                    )
                                    logger.info(
                                        f"Successfully initialized LLM with specific model for Kroki correction: {KROKI_CORRECTION_MODEL_NAME}"
                                    )
                                else:
                                    logger.warning(
                                        "Could not fetch default LLM provider details to use KROKI_CORRECTION_MODEL_NAME. "
                                        "Will attempt fallback to default LLM."
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to initialize LLM with KROKI_CORRECTION_MODEL_NAME "
                                    f"'{KROKI_CORRECTION_MODEL_NAME}': {e}. Will attempt fallback to default LLM."
                                )

                        # Fallback to the general default LLM if specific one wasn't created or not configured
                        if not correction_llm_instance:
                            logger.info(
                                "KROKI_CORRECTION_MODEL_NAME not configured or failed to initialize. "
                                "Falling back to default LLM for Kroki correction."
                            )
                            default_llm_instance, _ = get_default_llms()
                            correction_llm_instance = default_llm_instance
                        
                        llm_prompt = (
                            f"The following '{diagram_type}' diagram code produced a syntax error when processed by Kroki.\n\n"
                            f"Original Diagram Code (that caused the error):\n```\n{current_content}\n```\n\n"
                            f"Syntax Error Message from Kroki:\n```\n{kroki_error_message}\n```\n\n"
                            "Your task is to analyze the diagram code and the error message, then provide the corrected diagram code. "
                            "Focus on fixing the syntax to resolve the reported error. "
                            "IMPORTANT: Output ONLY the corrected diagram code. Do not include any explanations, apologies, or markdown formatting like ```diagram ... ```. "
                            "If the provided code is not '{diagram_type}' code, convert it into the closest representation you can into '{diagram_type}' code."
                            "If you cannot correct the code, or if the error seems unrelated to syntax you can fix, output the original code."   
                        )
                        
                        logger.info(
                            f"Attempting LLM correction for '{diagram_type}'. Prompt (first 200 chars): {llm_prompt[:200]}"
                        )

                        if correction_llm_instance:
                            llm_response = correction_llm_instance.invoke(prompt=llm_prompt)
                        else:
                            logger.error("No LLM instance could be obtained for Kroki correction.")
                            llm_response = None # Ensure llm_response is None if no instance, to avoid downstream errors
                        
                        if llm_response and isinstance(llm_response.content, str):
                            corrected_code_from_llm = llm_response.content
                        else:
                            corrected_code_from_llm = None
                            logger.warning(
                                f"LLM response for '{diagram_type}' was not as expected (no content or not string). "
                                f"Response: {llm_response}"
                            )

                    except GenAIDisabledException as gen_ai_err:
                        logger.error(
                            f"LLM call failed for '{diagram_type}' as Generative AI is disabled: {str(gen_ai_err)}. "
                            f"Original Kroki error: {kroki_error_message}"
                        )
                    except (LLMTimeoutError, LLMRateLimitError) as llm_infra_err:
                        logger.error(
                            f"LLM call failed for '{diagram_type}' due to LLM infrastructure error: {str(llm_infra_err)}. "
                            f"Original Kroki error: {kroki_error_message}"
                        )
                    except Exception as e: # General catch-all for other unexpected errors, including unhandled LLM issues
                        logger.error(
                            f"Unexpected error during LLM call for '{diagram_type}': {str(e)}. "
                            f"Original Kroki error: {kroki_error_message}",
                            exc_info=True
                        )
                        # Fallback: Unexpected error, proceed without correction for this attempt
                    
                    # --- END LLM CORRECTION IMPLEMENTATION ---

                    if corrected_code_from_llm and corrected_code_from_llm.strip() and corrected_code_from_llm.strip() != current_content.strip():
                        logger.info(
                            f"LLM provided a correction for '{diagram_type}'. Retrying with new content."
                        )
                        current_content = corrected_code_from_llm.strip()
                        continue  # Continue to the next iteration of the loop for the retry
                    else:
                        if corrected_code_from_llm:
                             logger.warning(
                                f"LLM did not provide a new/different correction for '{diagram_type}'. "
                                f"LLM output (first 100 chars): '{corrected_code_from_llm[:100]}...'. "
                                f"Original syntax error will be returned."
                            )
                        else:
                            logger.warning(
                                f"LLM did not provide any correction for '{diagram_type}' (e.g. LLM error or empty response). "
                                f"Original syntax error will be returned."
                            )
                        # If LLM doesn't help, or returns same/empty content, stop retrying for this syntax error.
                        return {"error": kroki_error_message, "error_type": "syntax"}
                else:
                    # Max retries reached for syntax error
                    logger.warning(
                        f"Max LLM retries ({KROKI_MAX_LLM_RETRIES}) reached for Kroki syntax error on '{diagram_type}', "
                        f"original hash: {content_hash}. Final error: {kroki_error_message}"
                    )
                    return {"error": kroki_error_message, "error_type": "syntax"}
            
            else: # Other non-200, non-400 status codes from Kroki
                error_text = response.text or f"Kroki service error (Status: {response.status_code})"
                logger.warning(
                    f"{log_message_prefix}: Kroki service returned status {response.status_code} for '{diagram_type}', "
                    f"original hash: {content_hash}. Response: {error_text}"
                )
                return {"error": "Diagram rendering failed due to Kroki service error", "error_type": "service"}
                
        except httpx.TimeoutException:
            logger.warning(
                f"{log_message_prefix}: Timeout when calling Kroki service for '{diagram_type}', "
                f"original hash: {content_hash}."
            )
            # Timeouts are not specified for LLM retry by the requirements.
            # This will be the final result for this call to _cached_kroki_request.
            return {"error": "Diagram rendering timeout", "error_type": "service"}
            
        except Exception as e:
            logger.error(
                f"{log_message_prefix}: Exception calling Kroki service for '{diagram_type}', "
                f"original hash: {content_hash}: {str(e)}", exc_info=True
            )
            # General exceptions are also not specified for LLM retry.
            return {"error": "Diagram rendering failed due to an unexpected error", "error_type": "service"}
            
    # This part should ideally not be reached if the loop logic correctly handles all attempts and outcomes.
    # It implies all attempts were exhausted without returning a definitive result from within the loop.
    logger.error(
        f"Fell through Kroki request loop for '{diagram_type}', original hash: {content_hash}. "
        "This indicates an unexpected issue in the retry logic."
    )
    return {"error": "Diagram rendering failed after all attempts", "error_type": "service"}

@router.head("/health")
def kroki_health_check() -> StatusResponse:
    """
    Health check endpoint to verify if Kroki functionality is available.
    Used by frontend to detect feature availability.
    """
    if not KROKI_ENABLED:
        raise HTTPException(status_code=404, detail="Kroki service not enabled")
    
    return StatusResponse(success=True, message="Kroki service available")

@router.post("/{diagram_type}")
def render_diagram(
    diagram_type: str,
    request: DiagramRequest
) -> Dict[str, Any]:
    """
    Proxy endpoint to render diagrams via Kroki service.
    
    Args:
        diagram_type: Type of diagram (mermaid, plantuml, etc.)
        request: Request containing diagram content
        
    Returns:
        Either SVG content or error information
    """
    if not KROKI_ENABLED:
        raise HTTPException(status_code=404, detail="Kroki service not enabled")
    
    if diagram_type not in SUPPORTED_DIAGRAM_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported diagram type: {diagram_type}. Supported types: {', '.join(sorted(SUPPORTED_DIAGRAM_TYPES))}"
        )
    
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Diagram content cannot be empty")
    
    # Create content hash for caching
    content_hash = hashlib.md5(request.content.encode()).hexdigest()
    
    try:
        result = _cached_kroki_request(diagram_type, content_hash, request.content)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in render_diagram: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Only register routes if Kroki is enabled
def kroki_router() -> APIRouter:
    """
    Returns the Kroki router only if the feature is enabled.
    If disabled, returns an empty router.
    """
    if KROKI_ENABLED:
        logger.info(f"Kroki service enabled with URL: {KROKI_URL}")
        return router
    else:
        logger.info("Kroki service disabled - KROKI_URL not configured")
        return APIRouter()  # Empty router when disabled
