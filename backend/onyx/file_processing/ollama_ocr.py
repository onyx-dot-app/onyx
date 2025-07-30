import io
import base64
from typing import IO, Any, Optional
from PIL import Image
import fitz  # PyMuPDF
import requests
import json

from onyx.utils.logger import setup_logger

logger = setup_logger()

class OllamaOCRExtractor:
    """OCR extraction using Ollama vision models."""
    
    def __init__(self, 
                 model_name: str = "llava:latest",
                 ollama_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.ollama_url = ollama_url
        self._check_ollama_availability()
    
    def _check_ollama_availability(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            # Check if Ollama is running
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.warning("Ollama server not accessible")
                return False
            
            # Check if model is available
            models = response.json().get("models", [])
            available_models = [model["name"] for model in models]
            
            if self.model_name not in available_models:
                logger.warning(f"Model {self.model_name} not found. Available: {available_models}")
                # Try to pull the model
                self._pull_model()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check Ollama availability: {e}")
            return False
    
    def _pull_model(self):
        """Pull the vision model if not available."""
        try:
            logger.info(f"Pulling model {self.model_name}...")
            response = requests.post(
                f"{self.ollama_url}/api/pull",
                json={"name": self.model_name},
                timeout=300  # 5 minutes for model download
            )
            if response.status_code == 200:
                logger.info(f"Successfully pulled {self.model_name}")
            else:
                logger.error(f"Failed to pull model: {response.text}")
        except Exception as e:
            logger.error(f"Error pulling model: {e}")
    
    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string."""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def _extract_text_from_image(self, image_bytes: bytes) -> str:
        """Extract text from a single image using Ollama vision model."""
        try:
            base64_image = self._image_to_base64(image_bytes)
            
            prompt = """Please extract all text from this image. 
            Return only the text content, maintaining the original formatting and structure.
            Do not add any commentary or explanations."""
            
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False
            }
            
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            else:
                logger.error(f"Ollama API error: {response.text}")
                return ""
                
        except Exception as e:
            logger.error(f"Error extracting text from image: {e}")
            return ""
    
    def extract_text_from_pdf(self, file: IO[Any]) -> str:
        """Extract text from PDF using Ollama OCR."""
        try:
            file.seek(0)
            pdf_document = fitz.open(stream=file.read(), filetype="pdf")
            logger.info(f"Processing PDF with {len(pdf_document)} pages using Ollama OCR")
            
            extracted_pages = []
            
            for page_num in range(len(pdf_document)):
                try:
                    logger.info(f"Processing page {page_num + 1}...")
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
        except Exception as e:
            logger.error(f"Failed to initialize Ollama OCR: {e}")
            return None
    return _ollama_ocr

def is_ollama_ocr_available() -> bool:
    """Check if Ollama OCR is available."""
    ocr = get_ollama_ocr()
    return ocr is not None
