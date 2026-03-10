"""
jsonriver - A streaming JSON parser for Python

Parse JSON incrementally as it streams in, e.g. from a network request or a language model.
Gives you a sequence of increasingly complete values.

Copyright (c) 2023 Google LLC (original TypeScript implementation)
Copyright (c) 2024 jsonriver-python contributors (Python port)
SPDX-License-Identifier: BSD-3-Clause
"""

from .parse import _Parser as Parser
from .parse import JsonObject
from .parse import JsonValue

__all__ = ["Parser", "JsonValue", "JsonObject"]
__version__ = "0.0.1"
