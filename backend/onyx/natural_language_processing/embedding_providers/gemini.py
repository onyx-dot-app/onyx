_GEMINI_EMBEDDING_2_MODEL_PREFIX = "gemini-embedding-2"

# Gemini embedding-2 ignores task_type entirely; instead the documented way
# to differentiate query vs. document is to wrap the input in Google's task
# instruction format. The exact templates come from
# https://ai.google.dev/gemini-api/docs/embeddings (Gemini Embedding 2 section).
_GEMINI_EMBEDDING_2_PROMPT_TEMPLATES = {
    "RETRIEVAL_QUERY": "task: search result | query: {text}",
    "RETRIEVAL_DOCUMENT": "title: none | text: {text}",
}


def gemini_base_model_name(model: str) -> str:
    """`publishers/google/models/gemini-embedding-2` and `gemini-embedding-2`
    are the same model."""
    return model.split("/")[-1].strip().lower()


def is_gemini_embedding_2_model(model: str) -> bool:
    return gemini_base_model_name(model).startswith(_GEMINI_EMBEDDING_2_MODEL_PREFIX)


def format_gemini_embedding_text(text: str, model: str, embedding_type: str) -> str:
    if not is_gemini_embedding_2_model(model):
        return text

    template = _GEMINI_EMBEDDING_2_PROMPT_TEMPLATES.get(embedding_type)
    if template is None:
        raise RuntimeError(
            f"Unsupported Gemini embedding-2 task type: {embedding_type}"
        )

    return template.format(text=text)
