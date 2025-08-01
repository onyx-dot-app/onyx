# File: backend/onyx/file_processing/ollama_ocr.py

import io
import base64
import os
from typing import IO, Any, Optional
from PIL import Image
import fitz  # PyMuPDF
import requests
import json

from onyx.utils.logger import setup_logger

logger = setup_logger()

class OllamaOCRExtractor:
    """OCR extraction using existing Ollama vision models."""
    
    def __init__(self, 
# <<<<<<< n-4t
#                  model_name: str = "llama3.2-vision:11b",
# =======
                 model_name: str = "granite3.2-vision",
# >>>>>>> main
                 ollama_url: str = None):
        # Try to detect Ollama URL from environment or use common defaults
        if ollama_url is None:
            ollama_url = self._detect_ollama_url()
        
        self.model_name = model_name
        self.ollama_url = ollama_url
        self.available = self._check_ollama_availability()
    
    def _detect_ollama_url(self) -> str:
        """Auto-detect Ollama URL from environment or common patterns."""
        # Check environment variables that Onyx might use for Ollama
        possible_env_vars = [
            'OLLAMA_URL',
            'OLLAMA_BASE_URL', 
            'OLLAMA_HOST',
            'LLM_PROVIDER_HOST',
            'OLLAMA_API_BASE'
        ]
        
        for env_var in possible_env_vars:
            url = os.getenv(env_var)
            if url:
                logger.info(f"Using Ollama URL from {env_var}: {url}")
                return url.rstrip('/')
        
        # Common Docker service names for Ollama in Onyx setups
        possible_urls = [
            "http://ollama:11434",      # Most common Docker Compose service name
            "http://localhost:11434",   # Local development
            "http://127.0.0.1:11434",   # Local alternative
            "http://onyx-ollama:11434", # Some setups use prefixed names
            "http://ollama-server:11434" # Alternative naming
            "http://host.docker.internal:11434"    # I THINK THIS IS WHAT IS USED IN THE THING SO WE BALL W ITTTTTTTTTTTTTTTTTTTTTTTTTTTTTTT
        ]
        
        for url in possible_urls:
            try:
                response = requests.get(f"{url}/api/tags", timeout=2)
                if response.status_code == 200:
                    logger.info(f"Found Ollama at: {url}")
                    return url
            except:
                continue
        
        logger.warning("Could not auto-detect Ollama URL, using default")
        return "http://host.docker.internal:11434"
    
    def _check_ollama_availability(self) -> bool:
        """Check if Ollama is running and has vision models available."""
        try:
            logger.info(f"Checking Ollama availability at {self.ollama_url}")
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.warning(f"Ollama server not accessible at {self.ollama_url}")
                return False
            
            # Check available models
            models = response.json().get("models", [])
            available_models = [model["name"] for model in models]
            logger.info(f"Available Ollama models: {available_models}")
            
            # Look for vision-capable models (in order of preference)
            vision_models = [
# <<<<<<< n-4t
#                 "llama3.2-vision:11b"
# =======
                "llama3.2-vision:11b",
		            "granite3.2-vision:latest"
# >>>>>>> main
                # "llava:latest", 
                # "llava:13b", 
                # "llava:7b",
                # "llava-phi3:latest",
                # "moondream:latest",
                # "bakllava:latest"
            ]
            
            for model in vision_models:
                if model in available_models:
                    self.model_name = model
                    logger.info(f"Using vision model: {model}")
                    return True
            
            # If requested model not found, try to find any llava model
            llava_models = [m for m in available_models if "llava" in m.lower()]
            if llava_models:
                self.model_name = llava_models[0]
                logger.info(f"Using available LLaVA model: {self.model_name}")
                return True
            
            logger.warning(f"No vision models found. Available models: {available_models}")
            logger.info("To add a vision model, run: docker exec your_ollama_container ollama pull llava:latest")
            return False
            
        except Exception as e:
            logger.warning(f"Ollama OCR not available: {e}")
            return False
    
    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string."""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def _extract_text_from_image(self, image_bytes: bytes) -> str:
        """Extract text from a single image using Ollama vision model."""
        try:
            base64_image = self._image_to_base64(image_bytes)
            
            prompt = """Please extract ALL text from this image exactly as it appears. 
            Maintain the original formatting, spacing, and structure.
            Include headers, paragraphs, bullet points, and any other text elements.
            Do not add explanations or commentary - only return the extracted text."""
            
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
                "options": {
                    "temperature": 0,  # More deterministic output
                    "top_p": 0.9
                }
            }
            
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=120  # Longer timeout for vision processing
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return ""
                
        except Exception as e:
            logger.error(f"Error extracting text from image: {e}")
            return ""
    
    def extract_text_from_pdf(self, file: IO[Any]) -> str:
        """Extract text from PDF using Ollama OCR."""
        if not self.available:
            logger.warning("Ollama OCR not available")
            return ""
            
        try:
            file.seek(0)
            pdf_document = fitz.open(stream=file.read(), filetype="pdf")
            logger.info(f"Processing PDF with {len(pdf_document)} pages using Ollama OCR (model: {self.model_name})")
            
            extracted_pages = []
            
            for page_num in range(len(pdf_document)):
                try:
                    logger.info(f"Processing page {page_num + 1} with Ollama OCR...")
                    page = pdf_document.load_page(page_num)
                    
                    # Render page as high-quality image
                    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    
                    # Extract text using Ollama
                    page_text = self._extract_text_from_image(img_bytes)
                    
                    if page_text.strip():
                        extracted_pages.append(f"=== Page {page_num + 1} ===\n{page_text}")
                        logger.info(f"Page {page_num + 1}: Extracted {len(page_text)} characters")
                    else:
                        extracted_pages.append(f"=== Page {page_num + 1} ===\n[No text detected]")
                        logger.warning(f"Page {page_num + 1}: No text detected")
                    
                except Exception as e:
                    logger.error(f"Error processing page {page_num + 1}: {e}")
                    extracted_pages.append(f"=== Page {page_num + 1} ===\n[Error: {str(e)}]")
            
            pdf_document.close()
            result = "\n\n".join(extracted_pages)
            logger.info(f"Ollama OCR completed - total text: {len(result)} characters")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process PDF with Ollama OCR: {e}")
            return ""


# Global instance
_ollama_ocr = None

def get_ollama_ocr() -> Optional[OllamaOCRExtractor]:
    """Get Ollama OCR instance if available."""
    global _ollama_ocr
    if _ollama_ocr is None:
        try:
            _ollama_ocr = OllamaOCRExtractor()
            if not _ollama_ocr.available:
                _ollama_ocr = None
        except Exception as e:
            logger.error(f"Failed to initialize Ollama OCR: {e}")
            return None
    return _ollama_ocr

def is_ollama_ocr_available() -> bool:
    """Check if Ollama OCR is available."""
    ocr = get_ollama_ocr()
    return ocr is not None and ocr.available
