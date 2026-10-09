"""Findings: structured information a capability check discovers about what a
credential and config reach, beside its pass/fail outcome.

A finding names what it describes with a closed ``key``; the frontend turns the
key into a localized label, so findings carry no display text. ``field_name``
names the config field a finding informs, for a form that offers the finding's
options in that field.

Findings stay conservative: names and ids of containers (drives, spaces,
channels, mailboxes) and counts. Never document content, and never lists of
people: users are a count.
"""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from onyx.utils.logger import setup_logger

logger = setup_logger()

# TODO: a search endpoint for sources whose listings exceed this.
MAX_FINDING_OPTIONS = 1000


class CheckFindingKey(str, Enum):
    SHARED_DRIVES = "shared_drives"
    IMPERSONATABLE_USERS = "impersonatable_users"
    VISIBLE_SPACES = "visible_spaces"
    READABLE_CHANNELS = "readable_channels"
    READABLE_MAILBOXES = "readable_mailboxes"
    READABLE_DRIVES = "readable_drives"


class CheckFindingType(str, Enum):
    COUNT = "count"
    OPTIONS = "options"


class CountFinding(BaseModel):
    type: Literal[CheckFindingType.COUNT] = CheckFindingType.COUNT
    key: CheckFindingKey
    field_name: str | None = None
    count: int = Field(ge=0)
    # The listing stopped at a cap, so the real count is at least ``count``.
    at_least: bool = False


class FindingOption(BaseModel):
    # What a form puts in the config field: an id or a URL.
    value: str
    # What the admin reads.
    label: str
    # An optional second line.
    detail: str | None = None


class OptionsFinding(BaseModel):
    type: Literal[CheckFindingType.OPTIONS] = CheckFindingType.OPTIONS
    key: CheckFindingKey
    field_name: str | None = None
    options: list[FindingOption] = Field(max_length=MAX_FINDING_OPTIONS)
    # The listing stopped at MAX_FINDING_OPTIONS.
    truncated: bool = False


CheckFinding = Annotated[CountFinding | OptionsFinding, Field(discriminator="type")]

_CHECK_FINDING_ADAPTER: TypeAdapter[CheckFinding] = TypeAdapter(CheckFinding)


def parse_known_findings(raw: Any) -> Any:
    """Keeps the findings this version understands. A stored finding with a
    newer type or key is dropped, not an error, so a report written by a newer
    version still reads."""
    if not isinstance(raw, list):
        return raw
    known: list[CheckFinding] = []
    for item in raw:
        try:
            known.append(_CHECK_FINDING_ADAPTER.validate_python(item))
        except ValidationError:
            logger.debug("Dropping an unknown capability check finding")
    return known
