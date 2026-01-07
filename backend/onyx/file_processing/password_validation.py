import io
from collections.abc import Callable
from typing import Any
from typing import IO

from onyx.file_processing.extract_file_text import get_file_ext

PASSWORD_PROTECTED_FILES = [
    "pdf",
    "docx",
    "pptx",
    "xlsx",
]


def is_pdf_protected(file: IO[Any]) -> bool:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file))
    return bool(reader.is_encrypted)


def is_docx_protected(file: IO[Any]) -> bool: ...


def is_pptx_protected(file: IO[Any]) -> bool: ...


def is_xlsx_protected(file: IO[Any]) -> bool: ...


def is_file_password_protected(
    file: IO[Any],
    file_name: str,
    extension: str | None = None,
) -> bool:
    extension_to_function: dict[str, Callable[[IO[Any]], str]] = {
        "pdf": is_pdf_protected,
    }

    if not extension:
        extension = get_file_ext(file_name)

    if extension not in PASSWORD_PROTECTED_FILES:
        return False

    func = extension_to_function[extension]
    return func(file)
