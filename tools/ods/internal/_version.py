from __future__ import annotations

import os
import re

_tag = os.environ.get("GITHUB_REF_NAME", "v0.0.0-dev").removeprefix("ods/")
_match = re.search(r"v?(\d+\.\d+\.\d+)", _tag)
__version__ = _match.group(1) if _match else "0.0.0"
