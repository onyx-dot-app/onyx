from typing import TypeVar

T = TypeVar("T")


def batch_list(
    lst: list[T],
    batch_size: int,
) -> list[list[T]]:
    return [lst[i : i + batch_size] for i in range(0, len(lst), batch_size)]


def clean_model_name(model_str: str) -> str:
    """Fold a model name into the form used in index names.

    Index names (`danswer_chunk_<cleaned>`) depend on this output, so it must
    never change.
    """
    return model_str.replace("/", "_").replace("-", "_").replace(".", "_").lower()
