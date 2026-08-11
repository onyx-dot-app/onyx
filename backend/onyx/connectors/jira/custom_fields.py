"""Reading Jira custom fields so their content can be indexed.

A lot of the information on a Jira issue lives in custom fields rather than in
the description: rich text fields holding deployment tables, select lists
holding release type or planned downtime, sprints, and so on. Jira returns them
under opaque ids (``customfield_13290``), so the human readable field name has
to be resolved separately through the ``/field`` endpoint.

Values arrive in whatever shape the field type uses (plain scalar, select option
object, user object, ADF document, list of any of those), so they are rendered
recursively. Anything that carries no readable text is omitted rather than
dumped into the index as raw JSON.
"""

from typing import Any

from jira import JIRA
from jira.resources import Issue
from pydantic import BaseModel

from onyx.connectors.jira.adf import extract_text_from_adf
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Custom field types whose values are machine state rather than content. These
# are matched as prefixes against ``schema.custom``.
_NOISE_CUSTOM_FIELD_TYPES: tuple[str, ...] = (
    # Board ordering token, e.g. "1|i0aps7:".
    "com.pyxis.greenhopper.jira:gh-lexo-rank",
    # Charting plugin fields ("[CHART] Time in Status") hold encoded status
    # histories, e.g. "3_*:*_1_*:*_0_*|*_13908_*:*_1_*:*_4418".
    "com.atlassian.jira.ext.charting:",
    # Commit/branch/PR roll-ups from the development tooling integration.
    "com.atlassian.jira.plugins.jira-development-integration-plugin:",
    # JSM SLA fields serialize as large goal/cycle structures.
    "com.atlassian.servicedesk:sd-sla-field",
    # Advanced Roadmaps bookkeeping (baselines, internal parent/team ids).
    "com.atlassian.jpo:jpo-custom-field-",
)

# Upper bound on a single rendered field. Rich text fields are usually the most
# valuable thing on an issue, so this is generous; it exists only so that one
# oversized field cannot crowd out every other field.
_MAX_FIELD_VALUE_CHARS = 20_000

_TRUNCATION_SUFFIX = " [truncated]"


class JiraFieldMetadata(BaseModel):
    """The parts of a Jira field definition needed to index its value."""

    id: str
    name: str
    # ``schema.custom``, e.g. "com.pyxis.greenhopper.jira:gh-sprint".
    custom_type: str | None = None

    @property
    def is_noise(self) -> bool:
        if self.custom_type is None:
            return False
        return self.custom_type.startswith(_NOISE_CUSTOM_FIELD_TYPES)


def get_custom_field_metadata(jira_client: JIRA) -> dict[str, JiraFieldMetadata]:
    """Fetch every custom field definition, keyed by field id.

    One request per connector run; the caller is expected to cache the result.
    """
    metadata_by_id: dict[str, JiraFieldMetadata] = {}
    for field in jira_client.fields():
        field_id = field.get("id")
        if not field.get("custom") or not field_id:
            continue
        field_schema = field.get("schema") or {}
        metadata_by_id[field_id] = JiraFieldMetadata(
            id=field_id,
            name=field.get("name") or field_id,
            custom_type=field_schema.get("custom"),
        )

    logger.debug("Resolved %s Jira custom field definitions", len(metadata_by_id))
    return metadata_by_id


def render_jira_field_value(value: Any) -> str:
    """Render a raw Jira field value (as found in ``issue.raw["fields"]``)."""
    if value is None:
        return ""
    # bool has to be checked before int, which it subclasses.
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        rendered_items = [
            rendered for item in value if (rendered := render_jira_field_value(item))
        ]
        if not rendered_items:
            return ""
        # Keep multi-line entries readable instead of running them together.
        separator = "\n" if any("\n" in item for item in rendered_items) else ", "
        return separator.join(rendered_items)
    if isinstance(value, dict):
        return _render_field_object(value)
    return ""


def _render_field_object(value: dict[str, Any]) -> str:
    """Render one of Jira's field value objects (option, user, sprint, ADF, ...)."""
    if value.get("type") == "doc":
        return extract_text_from_adf(value)

    # Select options expose "value", users "displayName", sprints/versions/groups
    # "name". Cascading selects nest the second level under "child".
    for key in ("value", "displayName", "name", "text"):
        rendered = render_jira_field_value(value.get(key))
        if not rendered:
            continue
        child = value.get("child")
        if isinstance(child, dict):
            child_rendered = _render_field_object(child)
            if child_rendered:
                return f"{rendered} - {child_rendered}"
        return rendered

    # Some plugin fields store an ADF fragment without the wrapping doc node.
    if isinstance(value.get("content"), list):
        return extract_text_from_adf(value)

    # Reference-only objects (just self/id) and opaque plugin state hold nothing
    # readable; indexing their JSON would only add noise.
    return ""


def render_issue_custom_fields(
    issue: Issue,
    custom_field_metadata: dict[str, JiraFieldMetadata],
    max_bytes: int,
) -> str:
    """Render an issue's populated custom fields as ``<name>: <value>`` text.

    Fields are emitted in name order so that re-indexing an unchanged issue
    produces identical content. The result is capped at ``max_bytes`` of UTF-8.
    """
    if max_bytes <= 0:
        return ""

    raw_fields = (issue.raw or {}).get("fields") or {}

    rendered_fields: list[tuple[str, str]] = []
    for field_id, raw_value in raw_fields.items():
        metadata = custom_field_metadata.get(field_id)
        if metadata is None or metadata.is_noise:
            continue
        rendered_value = render_jira_field_value(raw_value)
        if not rendered_value:
            continue
        rendered_fields.append((metadata.name, _cap_chars(rendered_value)))

    rendered_text = "\n".join(
        _format_field(name, value) for name, value in sorted(rendered_fields)
    )
    return _cap_utf8_bytes(rendered_text, max_bytes)


def _format_field(name: str, value: str) -> str:
    # Multi-line values (rich text, tables) read better under their own label.
    return f"{name}:\n{value}" if "\n" in value else f"{name}: {value}"


def _cap_chars(value: str) -> str:
    if len(value) <= _MAX_FIELD_VALUE_CHARS:
        return value
    return value[:_MAX_FIELD_VALUE_CHARS] + _TRUNCATION_SUFFIX


def _cap_utf8_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # errors="ignore" drops a partial character left at the cut point.
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
