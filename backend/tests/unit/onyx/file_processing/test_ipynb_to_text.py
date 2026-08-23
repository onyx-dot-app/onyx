import io
import json
from typing import Any

import pytest

from onyx.file_processing.extract_file_text import (
    extract_file_text,
    extract_text_and_images,
    ipynb_to_text,
)
from onyx.file_processing.file_types import OnyxFileExtensions, OnyxMimeTypes


def _create_notebook_bytes(notebook_dict: dict[str, Any]) -> io.BytesIO:
    return io.BytesIO(json.dumps(notebook_dict).encode("utf-8"))


def test_ipynb_file_types_registered() -> None:
    assert ".ipynb" in OnyxFileExtensions.DOCUMENT_EXTENSIONS
    assert ".ipynb" in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
    assert ".ipynb" in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
    assert "application/x-ipynb+json" in OnyxMimeTypes.DOCUMENT_MIME_TYPES
    assert "application/x-ipynb+json" in OnyxMimeTypes.ALLOWED_MIME_TYPES


def test_ipynb_to_text_basic_markdown_and_code() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "source": [
                    "# Analysis Title\n",
                    "This notebook demonstrates data exploration.",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "source": ["import math\n", "x = math.sqrt(16)\n", "print(x)"],
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": ["4.0\n"],
                    }
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 2,
    }

    file_bytes = _create_notebook_bytes(notebook)
    result = ipynb_to_text(file_bytes)

    assert "# Analysis Title\nThis notebook demonstrates data exploration." in result
    assert "```python\nimport math\nx = math.sqrt(16)\nprint(x)\n```" in result
    assert "Output:\n4.0" in result


def test_ipynb_to_text_execute_result_and_images() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 2,
                "source": "df.head()",
                "outputs": [
                    {
                        "output_type": "execute_result",
                        "execution_count": 2,
                        "data": {
                            "text/plain": ["   a  b\n0  1  2\n1  3  4"],
                            "text/html": ["<table>...</table>"],
                        },
                    },
                    {
                        "output_type": "display_data",
                        "data": {
                            "image/png": "base64_encoded_png_image_data_here",
                            "text/plain": ["<Figure size 640x480 with 1 Axes>"],
                        },
                    },
                ],
            }
        ]
    }

    file_bytes = _create_notebook_bytes(notebook)
    result = ipynb_to_text(file_bytes)

    assert "```python\ndf.head()\n```" in result
    assert "a  b\n0  1  2\n1  3  4" in result
    assert "<Figure size 640x480 with 1 Axes>" in result
    # Ensure raw image data is not included in plain text
    assert "base64_encoded_png_image_data_here" not in result


def test_ipynb_to_text_error_output() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 3,
                "source": "1 / 0",
                "outputs": [
                    {
                        "output_type": "error",
                        "ename": "ZeroDivisionError",
                        "evalue": "division by zero",
                        "traceback": [
                            "Traceback (most recent call last):",
                            "ZeroDivisionError: division by zero",
                        ],
                    }
                ],
            }
        ]
    }

    file_bytes = _create_notebook_bytes(notebook)
    result = ipynb_to_text(file_bytes)

    assert "```python\n1 / 0\n```" in result
    assert "ZeroDivisionError: division by zero" in result


def test_ipynb_to_text_raw_and_empty_cells() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "raw",
                "source": "Raw cell content here.",
            },
            {
                "cell_type": "markdown",
                "source": "   \n\t  ",
            },
            {
                "cell_type": "code",
                "source": "",
                "outputs": [],
            },
        ]
    }

    file_bytes = _create_notebook_bytes(notebook)
    result = ipynb_to_text(file_bytes)

    assert result == "Raw cell content here."


def test_ipynb_to_text_empty_source_with_outputs() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": "",
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": ["Output from cleared cell\n"],
                    }
                ],
            }
        ]
    }

    file_bytes = _create_notebook_bytes(notebook)
    result = ipynb_to_text(file_bytes)

    assert "Output:\nOutput from cleared cell" in result
    assert "```python" not in result


def test_ipynb_to_text_malformed_json_fallback() -> None:
    malformed = io.BytesIO(b"{ invalid json string")
    result = ipynb_to_text(malformed)
    assert result == "{ invalid json string"


def test_extract_file_text_and_extract_text_and_images_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        lambda: None,
    )

    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "source": "## Notebook Header",
            }
        ]
    }
    file_bytes = _create_notebook_bytes(notebook)

    # Test legacy extract_file_text
    extracted = extract_file_text(file_bytes, file_name="analysis.ipynb")
    assert "## Notebook Header" in extracted

    # Test extract_text_and_images
    file_bytes.seek(0)
    result = extract_text_and_images(file_bytes, file_name="analysis.ipynb")
    assert "## Notebook Header" in result.text_content
    assert result.embedded_images == []
