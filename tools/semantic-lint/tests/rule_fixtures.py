"""A temporary rules directory with the real settings and one rule."""

import shutil
import tempfile
import unittest
from pathlib import Path

from semantic_lint.registry import RULES_DIR, SETTINGS_FILE

RULE_ID = "backend-error-handling-silent-except"

RULE_TOML = """\
title = "Do not swallow an exception without a log line"
family = "other"
severity = "fix"
sources = [2528675138, 3344414001, 3624910226]
near_misses = [2496441566]
needs_repo_search = false
guidance = \"\"\"
Ask for at least a debug log in the except block, or a comment that says why
silence is safe.
\"\"\"

[scope]
paths = ["backend/**/*.py"]
exclude = ["backend/tests/**"]

[question]
instructions = "An added `except` block swallows the caught exception in silence."
true_what = "The body of an added `except` clause has no logger call and no `raise`."
false_what = "The `except` body calls a logger, re-raises, or explains the silence."
false_not_for = ["cleanup after a failure that is already logged"]

[[flag]]
comment = 2528675138
said = "this deserves at least a debug log"
code = '''
+            except ValidationError:
+                pass
'''

[[clean]]
comment = 2496441566
code = '''
+    except ValidationError:
+        return []  # not a tool call, which is the normal case
'''
"""


class RulesDirTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.rules_dir: Path = Path(temp.name)
        shutil.copy(RULES_DIR / SETTINGS_FILE, self.rules_dir / SETTINGS_FILE)
        self.rule_file: Path = self.rules_dir / f"{RULE_ID}.toml"
        self.rule_file.write_text(RULE_TOML)
