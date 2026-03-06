from __future__ import annotations

import os
import re

# Must match tag_prefix in pyproject.toml [tool.hatch.build.targets.wheel.hooks.custom]
TAG_PREFIX = "ods"

_tag = os.environ.get("GITHUB_REF_NAME", "v0.0.0-dev").removeprefix(f"{TAG_PREFIX}/")
_match = re.search(r"v?(\d+\.\d+\.\d+)", _tag)
__version__ = _match.group(1) if _match else "0.0.0"
