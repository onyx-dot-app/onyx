IMAGE_SUMMARIZATION_SYSTEM_PROMPT = """
You are an assistant for summarizing images for retrieval.
Summarize the content of the following image and be as precise as possible.
The summary will be embedded and used to retrieve the original image.
Therefore, write a concise summary of the image that is optimized for retrieval.
"""

IMAGE_SUMMARIZATION_USER_PROMPT = """
The image has the file name '{title}'.
Describe precisely and concisely what the image shows.
"""
