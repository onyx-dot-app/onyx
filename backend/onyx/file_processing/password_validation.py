from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from typing import IO

from onyx.file_processing.extract_file_text import get_file_ext
from onyx.utils.logger import setup_logger

logger = setup_logger()

PASSWORD_PROTECTED_FILES = [
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
]


@contextmanager
def preserve_position(file: IO[Any]) -> Generator[IO[Any], None, None]:
    """Preserves the file's cursor position"""
    pos = file.tell()
    try:
        file.seek(0)
        yield file
    finally:
        file.seek(pos)


def is_pdf_protected(file: IO[Any]) -> bool:
    from pypdf import PdfReader

    with preserve_position(file):
        reader = PdfReader(file)

    return bool(reader.is_encrypted)


def is_docx_protected(file: IO[Any]) -> bool:
    return is_office_file_protected(file)


def is_pptx_protected(file: IO[Any]) -> bool:
    return is_office_file_protected(file)


def is_xlsx_protected(file: IO[Any]) -> bool:
    return is_office_file_protected(file)


def is_office_file_protected(file: IO[Any]) -> bool:
    import msoffcrypto  # type: ignore[import-untyped]

    with preserve_position(file):
        office = msoffcrypto.OfficeFile(file)

    return office.is_encrypted()


def is_file_password_protected(
    file: IO[Any],
    file_name: str,
    extension: str | None = None,
) -> bool:
    extension_to_function: dict[str, Callable[[IO[Any]], bool]] = {
        ".pdf": is_pdf_protected,
        ".docx": is_docx_protected,
        ".pptx": is_pptx_protected,
        ".xlsx": is_xlsx_protected,
    }

    if not extension:
        extension = get_file_ext(file_name)

    if extension not in PASSWORD_PROTECTED_FILES:
        return False

    if extension not in extension_to_function:
        logger.warning(
            f"Extension={extension} can be password protected, but no function found"
        )
        return False

    func = extension_to_function[extension]

    return func(file)
