import hashlib
import logging
from functools import lru_cache
from typing import Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from onyx.auth.users import current_user
from onyx.configs.app_configs import KROKI_ENABLED
from onyx.configs.app_configs import KROKI_URL
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/kroki", dependencies=[Depends(current_user)])


class DiagramRequest(BaseModel):
    content: str


class DiagramResponse(BaseModel):
    svg: str


class DiagramErrorResponse(BaseModel):
    error: str
    error_type: str


# Supported diagram types by Kroki
SUPPORTED_DIAGRAM_TYPES = {
    "blockdiag", "seqdiag", "actdiag", "nwdiag", "packetdiag", "rackdiag",
    "graphviz", "pikchr", "erd", "excalidraw", "vega", "vegalite", 
    "ditaa", "mermaid", "nomnoml", "plantuml", "bpmn", "bytefield",
    "wavedrom", "svgbob", "c4plantuml", "structurizr", "umlet", 
    "wireviz", "symbolator"
}


@lru_cache(maxsize=128)
def _cached_kroki_request(diagram_type: str, content_hash: str, content: str) -> Dict[str, Any]:
    """
    Cached function to make requests to Kroki service.
    Uses content hash as part of cache key to ensure same content returns cached result.
    """
    if not KROKI_URL:
        raise HTTPException(status_code=503, detail="Kroki service not configured")
    
    try:
        # Make request to Kroki service
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{KROKI_URL}/{diagram_type}/svg",
                content=content,
                headers={"Content-Type": "text/plain"}
            )
            
            if response.status_code == 200:
                return {"svg": response.text}
            elif response.status_code == 400:
                # Syntax error in diagram
                error_msg = response.text or "Invalid diagram syntax"
                return {"error": error_msg, "error_type": "syntax"}
            else:
                # Service error
                logger.warning(f"Kroki service returned status {response.status_code}: {response.text}")
                return {"error": "Diagram rendering failed", "error_type": "service"}
                
    except httpx.TimeoutException:
        logger.warning(f"Timeout when calling Kroki service for {diagram_type}")
        return {"error": "Diagram rendering timeout", "error_type": "service"}
    except Exception as e:
        logger.error(f"Error calling Kroki service for {diagram_type}: {str(e)}")
        return {"error": "Diagram rendering failed", "error_type": "service"}


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
