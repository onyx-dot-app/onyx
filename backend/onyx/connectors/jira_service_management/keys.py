"""Project and issue keys that are safe to place in JQL and in a URL path.

Jira Data Center allows underscores and a maximum length the admin sets.
Cloud keys are a subset of the same pattern.
https://confluence.atlassian.com/adminjiraserver107/changing-the-project-key-format-1595114607.html
"""

import re

# Starts with a letter. The rest is letters, digits, or underscores.
# The cap is well above the default of 10 so a longer site setting still fits.
PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,99}$")
ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]+-\d+$")
