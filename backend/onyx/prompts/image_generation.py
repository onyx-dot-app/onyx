IMAGE_FILE_NAMING_SYSTEM_PROMPT = """
Given the image generation request, provide a SHORT name for the image. \
Focus the name on the important keywords that describe the subject. \
Make sure the name is in the same language as the request.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()

IMAGE_FILE_NAMING_USER_PROMPT = """
Image request: {prompt}

Provide a short name for this image.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()
