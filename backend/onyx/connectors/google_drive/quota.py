"""The Google quotas that the Drive connector spends, as the connector sees
them: which API a call counts against, and what it costs. The budgets
themselves come from the worker, through a ``SourceApiLimiter``."""

from enum import Enum


class DriveQuotaApi(str, Enum):
    """The APIs with a quota of their own."""

    DRIVE = "drive"
    DOCS = "docs"


# Drive API quota units. A list page costs the same at any page size.
DRIVE_LIST_UNITS = 100
DRIVE_READ_UNITS = 5
DRIVE_CONTENT_UNITS = 200
# The Docs API counts read requests.
DOCS_READ_UNITS = 1
