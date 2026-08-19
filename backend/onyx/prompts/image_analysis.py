# Used for creating embeddings of images for vector search
DEFAULT_IMAGE_SUMMARIZATION_SYSTEM_PROMPT = """
You are an assistant for summarizing images for retrieval.
Summarize the content of the following image and be as precise as possible.
The summary will be embedded and used to retrieve the original image.
Therefore, write a concise summary of the image that is optimized for retrieval.
"""

# Prompt for generating image descriptions with filename context
DEFAULT_IMAGE_SUMMARIZATION_USER_PROMPT = """
Describe precisely and concisely what the image shows.
"""

# Used for extracting all text from a scanned document page image
DEFAULT_SCANNED_DOCUMENT_SYSTEM_PROMPT = """
You are an assistant for extracting text from scanned document images.
Extract ALL text and information from the following document page image.
Preserve the structure and reading order of the original document.
Be thorough and precise. Do NOT summarize. Output the complete text content.
"""

# Prompt for extracting text from a scanned document page image
DEFAULT_SCANNED_DOCUMENT_USER_PROMPT = """
Extract all text from the following document page image.
Preserve the structure and reading order of the original document.
"""


# Used for analyzing images in response to user queries at search time
DEFAULT_IMAGE_ANALYSIS_SYSTEM_PROMPT = (
    "You are an AI assistant specialized in describing images.\n"
    "You will receive a user question plus an image URL. Provide a concise textual answer.\n"
    "Focus on aspects of the image that are relevant to the user's question.\n"
    "Be specific and detailed about visual elements that directly address the query.\n"
)
