from typing import TypeVar

T = TypeVar("T")


def batch_list(
    lst: list[T],
    batch_size: int,
) -> list[list[T]]:
    return [lst[i : i + batch_size] for i in range(0, len(lst), batch_size)]


def clean_model_name(model_str: str) -> str:
    """Fold a model name into the form used in index names
    (`danswer_chunk_<cleaned>`), so the output must never change."""
    return model_str.replace("/", "_").replace("-", "_").replace(".", "_").lower()
