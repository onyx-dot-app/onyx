import io
import base64
import os
import time
import threading
from typing import IO, Any, Optional
from PIL import Image
import fitz  # PyMuPDF
import requests
import json

from onyx.utils.logger import setup_logger

logger = setup_logger()

class OllamaOCRExtractor:
    """OCR extraction using existing Ollama vision models with improved error handling."""
    
    def __init__(self, 
#<<<<<<< HEAD
# <<<<<<< n-4t
#                  model_name: str = "llama3.2-vision:11b",
# =======
#                 model_name: str = "granite3.2-vision",
# >>>>>>> main
 #                ollama_url: str = None):
#=======
                 model_name: str = "granite3.2-vision:latest",
                 ollama_url: str = None,
                 max_retries: int = 3,
                 request_timeout: int = 180,
                 max_pages_per_pdf: int = 50):
#>>>>>>> f0cfc1c36 (idr modifying ollama_ocr.py but ig i did so im committing it)
        # Try to detect Ollama URL from environment or use common defaults
        if ollama_url is None:
            ollama_url = self._detect_ollama_url()
        
        self.model_name = model_name
        self.ollama_url = ollama_url
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.max_pages_per_pdf = max_pages_per_pdf
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
            "http://host.docker.internal:11434",    # Docker Desktop
            "http://ollama:11434",                  # Most common Docker Compose service name
            "http://localhost:11434",               # Local development
            "http://127.0.0.1:11434",              # Local alternative
            "http://onyx-ollama:11434",            # Some setups use prefixed names
            "http://ollama-server:11434"           # Alternative naming
        ]
        
        for url in possible_urls:
            try:
                response = requests.get(f"{url}/api/tags", timeout=5)
                if response.status_code == 200:
                    logger.info(f"Found Ollama at: {url}")
                    return url
            except Exception as e:
                logger.debug(f"Failed to connect to {url}: {e}")
                continue
        
        logger.warning("Could not auto-detect Ollama URL, using default")
        return "http://host.docker.internal:11434"
    
    def _check_ollama_availability(self) -> bool:
        """Check if Ollama is running and has vision models available."""
        try:
            logger.info(f"Checking Ollama availability at {self.ollama_url}")
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
            if response.status_code != 200:
                logger.warning(f"Ollama server not accessible at {self.ollama_url}")
                return False
            
            # Check available models
            models = response.json().get("models", [])
            available_models = [model["name"] for model in models]
            logger.info(f"Available Ollama models: {available_models}")
            
            # Look for vision-capable models (in order of preference)
            vision_models = [
#<<<<<<< HEAD
# <<<<<<< n-4t
#                 "llama3.2-vision:11b"
# =======
 #               "llama3.2-vision:11b",
#		            "granite3.2-vision:latest"
# >>>>>>> main
                # "llava:latest", 
                # "llava:13b", 
                # "llava:7b",
                # "llava-phi3:latest",
                # "moondream:latest",
                # "bakllava:latest"
#=======
                "granite3.2-vision:latest",
                "granite3.2-vision",
                "llama3.2-vision:11b",
                "llama3.2-vision:latest", 
                "llama3.2-vision"
    #            "llava:latest", 
     #           "llava:13b", 
 #               "llava:7b",
  #              "llava-phi3:latest",
   #             "moondream:latest",
    #            "bakllava:latest"
#>>>>>>> f0cfc1c36 (idr modifying ollama_ocr.py but ig i did so im committing it)
            ]
            
            for model in vision_models:
                if model in available_models:
                    self.model_name = model
                    logger.info(f"Using vision model: {model}")
                    return True
            
            # If requested model not found, try to find any vision model
            vision_keywords = ["llava", "vision", "granite", "moondream", "bakllava"]
            for model in available_models:
                if any(keyword in model.lower() for keyword in vision_keywords):
                    self.model_name = model
                    logger.info(f"Using available vision model: {self.model_name}")
                    return True
            
            logger.warning(f"No vision models found. Available models: {available_models}")
            logger.info("To add a vision model, run: docker exec your_ollama_container ollama pull granite3.2-vision:latest")
            return False
            
        except Exception as e:
            logger.error(f"Ollama OCR not available: {e}")
            return False
    
    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string with size validation."""
        # Check image size (Ollama has limits)
        max_size_mb = 10
        if len(image_bytes) > max_size_mb * 1024 * 1024:
            logger.warning(f"Image size {len(image_bytes)/1024/1024:.1f}MB exceeds {max_size_mb}MB, compressing...")
            try:
                # Compress image
                image = Image.open(io.BytesIO(image_bytes))
                # Reduce size while maintaining aspect ratio
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                
                # Save as JPEG with compression
                output = io.BytesIO()
                if image.mode in ('RGBA', 'LA', 'P'):
                    # Convert to RGB for JPEG
                    image = image.convert('RGB')
                image.save(output, format='JPEG', quality=85, optimize=True)
                image_bytes = output.getvalue()
                logger.info(f"Compressed image to {len(image_bytes)/1024/1024:.1f}MB")
            except Exception as e:
                logger.warning(f"Image compression failed: {e}")
        
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def _extract_text_from_image_with_timeout(self, image_bytes: bytes, timeout: int = 180) -> str:
        """Extract text from image with timeout mechanism."""
        result = {"text": "", "error": None}
        
        def extraction_worker():
            try:
                result["text"] = self._extract_text_from_image(image_bytes)
            except Exception as e:
                result["error"] = e
        
        thread = threading.Thread(target=extraction_worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            logger.error(f"OCR extraction timed out after {timeout} seconds")
            return "[OCR_TIMEOUT_ERROR]"
        
        if result["error"]:
            raise result["error"]
        
        return result["text"]
    
    def _extract_text_from_image(self, image_bytes: bytes) -> str:
        """Extract text from a single image using Ollama vision model."""
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"OCR attempt {attempt + 1}/{self.max_retries}")
                
                base64_image = self._image_to_base64(image_bytes)
                
                # Simplified, more reliable prompt
                prompt = """Extract all text from this image. Return only the text content without any explanations or comments."""
                
                payload = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "images": [base64_image],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 4096,  # Limit response length
                    }
                }
                
                logger.debug(f"Sending request to Ollama: {self.ollama_url}/api/generate")
                start_time = time.time()
                
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    timeout=self.request_timeout,
                    headers={'Content-Type': 'application/json'}
                )
                
                elapsed_time = time.time() - start_time
                logger.debug(f"Ollama response received in {elapsed_time:.1f}s")
                
                if response.status_code == 200:
                    result = response.json()
                    text = result.get("response", "").strip()
                    logger.debug(f"Extracted {len(text)} characters")
                    return text
                else:
                    logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return ""
                    
            except requests.exceptions.Timeout:
                logger.error(f"Request timeout after {self.request_timeout}s (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    time.sleep(5)
                    continue
                return "[REQUEST_TIMEOUT]"
            except requests.exceptions.ConnectionError:
                logger.error(f"Connection error to Ollama (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    time.sleep(5)
                    continue
                return "[CONNECTION_ERROR]"
            except Exception as e:
                logger.error(f"Error extracting text from image (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2)
                    continue
                return f"[ERROR: {str(e)}]"
        
        return ""
    
    def extract_text_from_pdf(self, file: IO[Any]) -> str:
        """Extract text from PDF using Ollama OCR with improved error handling."""
        if not self.available:
            logger.warning("Ollama OCR not available")
            return ""
            
        try:
            file.seek(0)
            pdf_data = file.read()
            pdf_document = fitz.open(stream=pdf_data, filetype="pdf")
            
            total_pages = len(pdf_document)
            logger.info(f"Processing PDF with {total_pages} pages using Ollama OCR (model: {self.model_name})")
            
            # Limit pages to prevent hanging
            pages_to_process = min(total_pages, self.max_pages_per_pdf)
            if total_pages > self.max_pages_per_pdf:
                logger.warning(f"PDF has {total_pages} pages, limiting to {self.max_pages_per_pdf} pages")
            
            extracted_pages = []
            
            for page_num in range(pages_to_process):
                try:
                    logger.info(f"Processing page {page_num + 1}/{pages_to_process}...")
                    start_time = time.time()
                    
                    page = pdf_document.load_page(page_num)
                    
                    # Get page dimensions to avoid huge images
                    rect = page.rect
                    if rect.width > 3000 or rect.height > 3000:
                        # Scale down large pages
                        scale = min(3000/rect.width, 3000/rect.height)
                        mat = fitz.Matrix(scale, scale)
                    else:
                        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
                    
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    
                    logger.debug(f"Page {page_num + 1} image size: {len(img_bytes)/1024/1024:.1f}MB")
                    
                    # Extract text using Ollama with timeout
                    page_text = self._extract_text_from_image_with_timeout(
                        img_bytes, 
                        timeout=self.request_timeout
                    )
                    
                    elapsed_time = time.time() - start_time
                    
                    if page_text and not page_text.startswith('[') and not page_text.endswith('_ERROR]'):
                        extracted_pages.append(f"=== Page {page_num + 1} ===\n{page_text}")
                        logger.info(f"Page {page_num + 1}: Extracted {len(page_text)} characters in {elapsed_time:.1f}s")
                    else:
                        extracted_pages.append(f"=== Page {page_num + 1} ===\n[No text detected or error occurred]")
                        logger.warning(f"Page {page_num + 1}: Failed to extract text - {page_text}")
                    
                    # Small delay between pages to prevent overwhelming Ollama
                    time.sleep(1)
                    
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
