import re
from datetime import datetime, timezone
from typing import Any

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.jira_service_management.models import (
    JsmAttachment,
    JsmChangelogEntry,
    JsmComment,
    SlaMetric,
)
from onyx.connectors.models import BasicExpertInfo
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_jsm_browse_url(base_url: str, issue_key: str) -> str:
    """Canonical URL for a JSM issue/request in Jira."""
    return f"{base_url.rstrip('/')}/browse/{issue_key}"


def build_jsm_portal_url(
    base_url: str, service_desk_id: str | None, issue_key: str
) -> str:
    """Customer portal URL when service_desk_id is known, else browse URL."""
    base = base_url.rstrip("/")
    if service_desk_id:
        return f"{base}/servicedesk/customer/portal/{service_desk_id}/{issue_key}"
    return build_jsm_browse_url(base, issue_key)


def best_effort_basic_expert_info(obj: Any) -> BasicExpertInfo | None:
    if not obj:
        return None
    display_name: str | None = None
    email: str | None = None
    try:
        if isinstance(obj, dict):
            display_name = obj.get("displayName") or obj.get("name")
            email = obj.get("emailAddress")
        else:
            display_name = getattr(obj, "displayName", None)  # ods: ignore[getattr]
            if not display_name:
                display_name = getattr(obj, "name", None)  # ods: ignore[getattr]
            email = getattr(obj, "emailAddress", None)  # ods: ignore[getattr]
    except Exception:
        return None

    if not email and not display_name:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


def extract_text_from_adf(adf: dict[str, Any] | None) -> str:
    """Extracts plain text from Atlassian Document Format (ADF)."""
    texts: list[str] = []

    def _extract(node: dict[str, Any]) -> None:
        node_type = node.get("type")
        if node_type == "text":
            text = node.get("text", "")
            if text:
                texts.append(str(text))
        elif node_type == "hardBreak":
            texts.append("\n")
        elif node_type in ("inlineCard", "blockCard", "embedCard"):
            attrs = node.get("attrs")
            if isinstance(attrs, dict) and isinstance(attrs.get("url"), str):
                texts.append(attrs["url"])
        elif node_type == "mention":
            attrs = node.get("attrs")
            if isinstance(attrs, dict) and isinstance(attrs.get("text"), str):
                texts.append(attrs["text"])
        for child in node.get("content", []):
            if isinstance(child, dict):
                _extract(child)

    if isinstance(adf, dict):
        _extract(adf)
    return " ".join(texts).strip()


def rich_text(value: Any) -> str:
    """Plain text from a JSM / Jira rich-text value (str, ADF dict, or HTML dict)."""
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if "<" in stripped and ">" in stripped:
            return parse_html_page_basic(stripped).strip()
        return stripped
    if isinstance(value, dict):
        if "html" in value and isinstance(value["html"], str):
            return parse_html_page_basic(value["html"]).strip()
        if "type" in value or "content" in value:
            return extract_text_from_adf(value)
        if "value" in value:
            return rich_text(value["value"])
        if "name" in value and isinstance(value["name"], str):
            return value["name"].strip()
    if isinstance(value, list):
        parts = [rich_text(item) for item in value]
        return ", ".join(p for p in parts if p)
    return str(value).strip()


def parse_jsm_datetime(value: Any) -> datetime | None:
    """Parses JSM date objects (`{'iso8601': ..., 'epochMillis': ...}`), ISO strings, or epochs."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            if value.tzinfo
            else value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, dict):
        iso_str = value.get("iso8601") or value.get("jira")
        if isinstance(iso_str, str) and iso_str:
            parsed = parse_jsm_datetime(iso_str)
            if parsed is not None:
                return parsed
        epoch_ms = value.get("epochMillis")
        if isinstance(epoch_ms, (int, float)):
            return datetime.fromtimestamp(float(epoch_ms) / 1000.0, tz=timezone.utc)
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return time_str_to_utc(raw)
        except Exception:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return (
                    dt.astimezone(timezone.utc)
                    if dt.tzinfo
                    else dt.replace(tzinfo=timezone.utc)
                )
            except ValueError:
                return None
    return None


def _friendly_duration(duration_obj: Any) -> str | None:
    if isinstance(duration_obj, dict):
        friendly = duration_obj.get("friendly")
        if isinstance(friendly, str) and friendly.strip():
            return friendly.strip()
        millis = duration_obj.get("millis")
        if isinstance(millis, (int, float)):
            minutes = int(millis // 60000)
            return f"{minutes}m"
    return None


def _parse_single_sla(raw_sla: dict[str, Any]) -> SlaMetric | None:
    name = raw_sla.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    ongoing = raw_sla.get("ongoingCycle")
    completed_list = raw_sla.get("completedCycles") or []

    cycle: dict[str, Any] | None = None
    is_ongoing = False
    if isinstance(ongoing, dict) and ongoing:
        cycle = ongoing
        is_ongoing = True
    elif isinstance(completed_list, list) and completed_list:
        last_completed = completed_list[-1]
        if isinstance(last_completed, dict):
            cycle = last_completed

    if cycle is None:
        return SlaMetric(name=name.strip(), is_ongoing=False)

    breached = cycle.get("breached")
    paused = cycle.get("paused")
    within_cal = cycle.get("withinCalendarHours")
    return SlaMetric(
        name=name.strip(),
        breached=bool(breached) if isinstance(breached, bool) else None,
        paused=bool(paused) if isinstance(paused, bool) else None,
        within_calendar_hours=(
            bool(within_cal) if isinstance(within_cal, bool) else None
        ),
        goal_duration=_friendly_duration(cycle.get("goalDuration")),
        elapsed_time=_friendly_duration(cycle.get("elapsedTime")),
        remaining_time=_friendly_duration(cycle.get("remainingTime")),
        is_ongoing=is_ongoing,
    )


def extract_sla_metrics(
    sla_values: list[dict[str, Any]] | None = None,
    issue_fields: dict[str, Any] | None = None,
) -> list[SlaMetric]:
    """Extracts SLA metrics from JSM `/sla` values and/or Jira issue custom SLA fields."""
    metrics_by_name: dict[str, SlaMetric] = {}

    for raw in sla_values or []:
        if isinstance(raw, dict):
            metric = _parse_single_sla(raw)
            if metric and metric.name not in metrics_by_name:
                metrics_by_name[metric.name] = metric

    if isinstance(issue_fields, dict):
        for field_val in issue_fields.values():
            if isinstance(field_val, dict) and (
                "ongoingCycle" in field_val or "completedCycles" in field_val
            ):
                metric = _parse_single_sla(field_val)
                if metric and metric.name not in metrics_by_name:
                    metrics_by_name[metric.name] = metric

    return list(metrics_by_name.values())


def format_sla_section(sla_metrics: list[SlaMetric]) -> str:
    """Formats SLA metrics into a human-readable text block."""
    if not sla_metrics:
        return ""
    lines: list[str] = ["SLA Metrics:"]
    for metric in sla_metrics:
        breach_tag = " [BREACHED]" if metric.breached else ""
        details: list[str] = []
        if metric.goal_duration:
            details.append(f"goal={metric.goal_duration}")
        if metric.elapsed_time:
            details.append(f"elapsed={metric.elapsed_time}")
        if metric.remaining_time:
            details.append(f"remaining={metric.remaining_time}")
        detail_str = f" ({', '.join(details)})" if details else ""
        lines.append(f"- {metric.name}: {metric.status}{breach_tag}{detail_str}")
    return "\n".join(lines)


def populate_sla_metadata(
    sla_metrics: list[SlaMetric],
    metadata_dict: dict[str, str | list[str]],
) -> None:
    if not sla_metrics:
        return
    metadata_dict["sla_names"] = [m.name for m in sla_metrics]
    any_breached = any(m.breached is True for m in sla_metrics)
    metadata_dict["sla_breached"] = str(any_breached).lower()
    metadata_dict["sla_status"] = "BREACHED" if any_breached else "MET"
    summaries: list[str] = []
    for m in sla_metrics:
        summaries.append(f"{m.name}: {m.status}")
        slug = re.sub(r"[^a-z0-9]+", "_", m.name.lower()).strip("_")
        if slug:
            metadata_dict[f"sla_{slug}"] = m.status
    metadata_dict["sla_summary"] = summaries


def extract_jsm_comments(
    jsm_comments: list[dict[str, Any]] | None = None,
    issue_fields: dict[str, Any] | None = None,
    include_internal_comments: bool = True,
    comment_email_blacklist: tuple[str, ...] = (),
) -> list[JsmComment]:
    """Extracts and deduplicates comments from JSM `/comment` API and/or Jira `fields.comment`."""
    blacklist_lower = {email.lower() for email in comment_email_blacklist if email}
    seen_ids: set[str] = set()
    result: list[JsmComment] = []

    raw_list: list[dict[str, Any]] = []
    if jsm_comments:
        raw_list.extend(c for c in jsm_comments if isinstance(c, dict))

    if isinstance(issue_fields, dict):
        comment_container = issue_fields.get("comment")
        if isinstance(comment_container, dict):
            for c in comment_container.get("comments") or []:
                if isinstance(c, dict):
                    raw_list.append(c)

    for raw in raw_list:
        comment_id = str(raw.get("id") or "")
        if comment_id and comment_id in seen_ids:
            continue

        # Determine public vs internal (JSM uses `public`, Jira issue uses `jsdPublic`)
        is_public = raw.get("public")
        if is_public is None:
            is_public = raw.get("jsdPublic", True)
        is_public_bool = bool(is_public)

        if not include_internal_comments and not is_public_bool:
            continue

        author = raw.get("author") or {}
        author_email: str | None = None
        author_name: str | None = None
        if isinstance(author, dict):
            author_email = author.get("emailAddress")
            author_name = author.get("displayName") or author.get("name")

        if author_email and author_email.lower() in blacklist_lower:
            continue

        body_text = rich_text(raw.get("body"))
        if not body_text:
            continue

        created_raw = raw.get("created")
        created_str: str | None = None
        if isinstance(created_raw, dict):
            created_str = created_raw.get("iso8601") or created_raw.get("friendly")
        elif isinstance(created_raw, str):
            created_str = created_raw

        if comment_id:
            seen_ids.add(comment_id)

        result.append(
            JsmComment(
                id=comment_id or str(len(result) + 1),
                author_name=author_name,
                author_email=author_email,
                body=body_text,
                public=is_public_bool,
                created=created_str,
            )
        )

    return result


def format_comments_section(comments: list[JsmComment]) -> str:
    if not comments:
        return ""
    lines: list[str] = ["Comments:"]
    for comment in comments:
        visibility = "[Public Reply]" if comment.public else "[Internal Note]"
        author_label = comment.author_name or comment.author_email or "Unknown"
        header = f"- {visibility} {author_label}"
        if comment.created:
            header += f" ({comment.created})"
        lines.append(f"{header}: {comment.body}")
    return "\n".join(lines)


def extract_changelog_entries(
    histories: list[dict[str, Any]] | None,
) -> list[JsmChangelogEntry]:
    if not histories:
        return []
    entries: list[JsmChangelogEntry] = []
    for history in histories:
        if not isinstance(history, dict):
            continue
        history_id = str(history.get("id") or "") or None
        author = history.get("author") or {}
        author_name = (
            author.get("displayName") or author.get("name")
            if isinstance(author, dict)
            else None
        )
        created = history.get("created")
        created_str = str(created) if isinstance(created, str) else None
        for item in history.get("items") or []:
            if not isinstance(item, dict):
                continue
            field_name = item.get("field")
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            from_str = item.get("fromString")
            to_str = item.get("toString")
            entries.append(
                JsmChangelogEntry(
                    id=history_id,
                    author_name=author_name,
                    created=created_str,
                    field=field_name.strip(),
                    from_string=str(from_str) if from_str is not None else None,
                    to_string=str(to_str) if to_str is not None else None,
                )
            )
    return entries


def format_changelog_section(entries: list[JsmChangelogEntry]) -> str:
    if not entries:
        return ""
    lines: list[str] = ["Changelog:"]
    for entry in entries:
        actor = f" by {entry.author_name}" if entry.author_name else ""
        when = f" [{entry.created}]" if entry.created else ""
        from_val = f"'{entry.from_string}'" if entry.from_string else "None"
        to_val = f"'{entry.to_string}'" if entry.to_string else "None"
        lines.append(f"- {entry.field}: {from_val} -> {to_val}{actor}{when}")
    return "\n".join(lines)


def extract_attachments(
    jsm_attachments: list[dict[str, Any]] | None = None,
    issue_fields: dict[str, Any] | None = None,
) -> list[JsmAttachment]:
    seen_keys: set[str] = set()
    attachments: list[JsmAttachment] = []

    raw_items: list[dict[str, Any]] = []
    if jsm_attachments:
        raw_items.extend(a for a in jsm_attachments if isinstance(a, dict))
    if isinstance(issue_fields, dict):
        for a in issue_fields.get("attachment") or []:
            if isinstance(a, dict):
                raw_items.append(a)

    for raw in raw_items:
        filename = raw.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            continue
        att_id = str(raw.get("id") or "")
        links = raw.get("_links") or {}
        content_url = (
            raw.get("content")
            or (links.get("content") if isinstance(links, dict) else None)
            or None
        )
        dedup_key = att_id or f"{filename}:{content_url or ''}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        author = raw.get("author") or {}
        author_name = (
            author.get("displayName") or author.get("name")
            if isinstance(author, dict)
            else None
        )
        created_raw = raw.get("created")
        created_str: str | None = None
        if isinstance(created_raw, dict):
            created_str = created_raw.get("iso8601") or created_raw.get("friendly")
        elif isinstance(created_raw, str):
            created_str = created_raw

        size_val = raw.get("size")
        attachments.append(
            JsmAttachment(
                id=att_id or filename.strip(),
                filename=filename.strip(),
                mime_type=raw.get("mimeType"),
                size=int(size_val) if isinstance(size_val, int) else None,
                content_url=str(content_url) if content_url else None,
                created=created_str,
                author_name=author_name,
            )
        )
    return attachments


def extract_rich_text(value: Any) -> str:
    return rich_text(value)


def extract_sla_metrics_from_jsm_payload(
    sla_values: list[dict[str, Any]] | None,
) -> list[SlaMetric]:
    return extract_sla_metrics(sla_values=sla_values)


def extract_sla_from_issue_fields(
    issue_fields: dict[str, Any] | None,
) -> list[SlaMetric]:
    return extract_sla_metrics(issue_fields=issue_fields)


def extract_comments_from_jsm_payload(
    jsm_comments: list[dict[str, Any]] | None,
    include_internal: bool = True,
    email_blacklist: set[str] | tuple[str, ...] | None = None,
) -> list[JsmComment]:
    return extract_jsm_comments(
        jsm_comments=jsm_comments,
        include_internal_comments=include_internal,
        comment_email_blacklist=tuple(email_blacklist or ()),
    )


def extract_comments_from_issue_fields(
    issue_fields: dict[str, Any] | None,
    include_internal: bool = True,
    email_blacklist: set[str] | tuple[str, ...] | None = None,
) -> list[JsmComment]:
    return extract_jsm_comments(
        issue_fields=issue_fields,
        include_internal_comments=include_internal,
        comment_email_blacklist=tuple(email_blacklist or ()),
    )


def extract_attachments_from_issue(
    issue_fields: dict[str, Any] | None,
) -> list[JsmAttachment]:
    return extract_attachments(issue_fields=issue_fields)


def extract_attachments_from_jsm_payload(
    jsm_attachments: list[dict[str, Any]] | None,
) -> list[JsmAttachment]:
    return extract_attachments(jsm_attachments=jsm_attachments)
