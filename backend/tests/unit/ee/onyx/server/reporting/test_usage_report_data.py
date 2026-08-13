"""Aggregation behind the usage report review pack."""

from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage
from pypdf import PdfReader

from ee.onyx.server.reporting.usage_report_branding import ReportBranding
from ee.onyx.server.reporting.usage_report_data import (
    TOP_USER_LIMIT,
    UsageReportData,
    build_usage_report_data,
)
from ee.onyx.server.reporting.usage_report_pdf import (
    _axis_labels,
    _display_name,
    render_usage_report_pdf,
)
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.user_usage import DELETED_USER_EXPORT_EMAIL, UsageExportRow

_BRANDING = ReportBranding(application_name="Acme Intelligence", logo=None)

PERIOD_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _row(
    email: str,
    cost: float = 10.0,
    day: str = "2026-07-01",
    flow: str = "chat",
    incognito: bool = False,
) -> UsageExportRow:
    return UsageExportRow(
        email=email,
        model="gpt-5",
        flow=flow,
        provider="openai",
        incognito=incognito,
        day=day,
        input_tokens=100,
        output_tokens=50,
        cache_read_tokens=10,
        cost_cents=cost,
    )


def _user(
    email: str,
    is_active: bool = True,
    account_type: AccountType = AccountType.STANDARD,
) -> User:
    user = User()
    user.email = email
    user.is_active = is_active
    user.account_type = account_type
    return user


def _build(rows: list[UsageExportRow], users: list[User]) -> UsageReportData:
    with patch(
        "ee.onyx.server.reporting.usage_report_data.get_all_users", return_value=users
    ):
        return build_usage_report_data(
            db_session=MagicMock(),
            rows=rows,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )


def test_totals_reconcile_with_the_rows() -> None:
    """The pack's totals must equal the CSV's, including deleted-user spend."""
    rows = [
        _row("a@x.com", 10.0),
        _row("b@x.com", 5.5),
        _row(DELETED_USER_EXPORT_EMAIL, 4.5),
    ]

    data = _build(rows, [_user("a@x.com"), _user("b@x.com")])

    assert data.total_cost_cents == pytest.approx(20.0)
    assert sum(e.cost_cents for e in data.by_model) == pytest.approx(20.0)
    assert sum(e.cost_cents for e in data.by_flow) == pytest.approx(20.0)
    assert sum(e.cost_cents for e in data.top_users) == pytest.approx(20.0)
    assert data.total_input_tokens == 300


def test_deleted_user_counts_toward_spend_but_is_not_a_person() -> None:
    rows = [_row("a@x.com"), _row(DELETED_USER_EXPORT_EMAIL)]

    data = _build(rows, [_user("a@x.com")])

    assert data.active_users == 1
    assert data.daily[0].active_users == 1
    assert data.total_cost_cents == pytest.approx(20.0)


def test_api_key_usage_is_not_an_active_user() -> None:
    """Seats exclude API-key users, so activity must exclude them too, or
    active_users can exceed licensed_users."""
    rows = [_row("a@x.com"), _row("somekey@onyxapikey.ai")]

    data = _build(rows, [_user("a@x.com")])

    assert data.active_users == 1
    assert data.active_users <= data.licensed_users


def test_unlabeled_flow_is_grouped_as_other() -> None:
    data = _build([_row("a@x.com", flow="")], [_user("a@x.com")])

    assert [(entry.name, entry.cost_cents) for entry in data.by_flow] == [
        ("other", 10.0)
    ]


def test_service_accounts_do_not_hold_a_seat() -> None:
    users = [
        _user("human@x.com"),
        _user("bot@x.com", account_type=AccountType.SERVICE_ACCOUNT),
        _user("gone@x.com", is_active=False),
    ]

    data = _build([_row("human@x.com")], users)

    assert data.licensed_users == 1
    assert data.seated_active_users == 1
    assert data.dormant_users == []


def test_a_deactivated_user_is_active_but_holds_no_seat() -> None:
    """Someone who used it mid-period and was deactivated before the report ran
    counts as a person, not as an occupied seat. The meter must not read
    "2 of 1 seats active"."""
    rows = [_row("stayed@x.com"), _row("departed@x.com")]
    users = [_user("stayed@x.com"), _user("departed@x.com", is_active=False)]

    data = _build(rows, users)

    assert data.active_users == 2
    assert data.licensed_users == 1
    assert data.seated_active_users == 1
    assert data.seated_active_users <= data.licensed_users


def test_dormant_seats_are_named() -> None:
    users = [_user("active@x.com"), _user("idle@x.com")]

    data = _build([_row("active@x.com")], users)

    assert data.licensed_users == 2
    assert data.active_users == 1
    assert data.dormant_users == ["idle@x.com"]


def test_top_users_folds_the_tail_and_preserves_the_total() -> None:
    rows = [_row(f"u{i}@x.com", cost=float(i + 1)) for i in range(TOP_USER_LIMIT + 3)]

    data = _build(rows, [])

    assert len(data.top_users) == TOP_USER_LIMIT + 1
    assert data.top_users[-1].name == "Other (3)"
    assert sum(e.cost_cents for e in data.top_users) == pytest.approx(
        data.total_cost_cents
    )


def test_a_single_extra_user_is_named_rather_than_folded() -> None:
    """Folding one entry hides a name and saves no space."""
    rows = [_row(f"u{i}@x.com", cost=float(i + 1)) for i in range(TOP_USER_LIMIT + 1)]

    data = _build(rows, [])

    assert not any(e.name.startswith("Other") for e in data.top_users)


def test_api_key_spend_is_labeled_by_key_name() -> None:
    """Per-key spend stays in the breakdown; only the label is cleaned up."""
    # A DB check constraint lowercases stored emails, so this is the real shape.
    assert (
        _display_name("api_key__nightly-sync@2f3c8a10-uuid.onyxapikey.ai")
        == "nightly-sync (API key)"
    )
    assert (
        _display_name("API_KEY__nightly-sync@2f3c8a10-uuid.onyxapikey.ai")
        == "nightly-sync (API key)"
    )
    assert (
        _display_name("api_key__sync@corp@2f3c8a10-uuid.onyxapikey.ai")
        == "sync@corp (API key)"
    )
    assert _display_name("human@corp.com") == "human@corp.com"
    assert _display_name("gpt-5") == "gpt-5"
    assert _display_name(DELETED_USER_EXPORT_EMAIL) == DELETED_USER_EXPORT_EMAIL


def test_api_key_spend_still_reconciles_after_relabeling() -> None:
    rows = [_row("a@x.com", 10.0), _row("api_key__bot@uuid.onyxapikey.ai", 90.0)]

    data = _build(rows, [_user("a@x.com")])

    assert data.total_cost_cents == pytest.approx(100.0)
    assert sum(e.cost_cents for e in data.top_users) == pytest.approx(100.0)
    assert data.active_users == 1


def test_zero_usage_still_renders_a_pdf() -> None:
    data = _build([], [_user("idle@x.com")])

    assert not data.has_usage
    assert data.cost_per_active_user_cents == 0.0
    assert render_usage_report_pdf(data, _BRANDING).startswith(b"%PDF-")


def test_application_name_is_not_parsed_as_markup() -> None:
    """ReportLab Paragraph parses a markup subset: an unescaped name with a tag
    silently drops text, injects formatting, or raises and loses the PDF."""
    data = _build([_row("a@x.com")], [_user("a@x.com")])

    for name in ["Tools <R> Us", "Acme <b>Corp", 'X <font color="red">Y</font>']:
        branding = ReportBranding(application_name=name, logo=None)
        pdf = render_usage_report_pdf(data, branding)
        assert pdf.startswith(b"%PDF-")


def _png(width: int = 40, height: int = 10) -> bytes:
    buffer = BytesIO()
    PILImage.new("RGBA", (width, height), (0, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_cover_is_unnumbered_and_later_pages_are_not() -> None:
    """A folio on the cover, or an off-by-one, corrupts every generated pack."""
    rows = [_row(f"u{i}@x.com", cost=float(i + 1)) for i in range(12)]
    data = _build(rows, [_user(f"u{i}@x.com") for i in range(12)])

    reader = PdfReader(BytesIO(render_usage_report_pdf(data, _BRANDING)))
    total = len(reader.pages)

    assert total > 1
    assert f"1 of {total}" not in reader.pages[0].extract_text()
    for number in range(2, total + 1):
        assert f"{number} of {total}" in reader.pages[number - 1].extract_text()


def test_render_is_deterministic() -> None:
    data = _build([_row("a@x.com")], [_user("a@x.com")])

    assert render_usage_report_pdf(data, _BRANDING) == render_usage_report_pdf(
        data, _BRANDING
    )


def test_render_is_deterministic_with_an_embedded_logo() -> None:
    """The default path embeds a logo, so determinism must hold with one."""
    data = _build([_row("a@x.com")], [_user("a@x.com")])
    branding = ReportBranding(application_name="Acme", logo=_png())

    assert render_usage_report_pdf(data, branding) == render_usage_report_pdf(
        data, branding
    )


def test_unreadable_logo_still_produces_a_pdf() -> None:
    """A corrupt upload must cost the branding, not the report."""
    data = _build([_row("a@x.com")], [_user("a@x.com")])

    for logo in (b"not-an-image", b""):
        branding = ReportBranding(application_name="Acme", logo=logo)
        assert render_usage_report_pdf(data, branding).startswith(b"%PDF-")


def test_axis_labels_never_exceed_the_display_limit() -> None:
    for day_count in (0, 1, 12, 13, 23, 24, 25, 30, 365):
        days = [f"2026-07-{day + 1:02d}" for day in range(day_count)]

        assert sum(bool(label) for label in _axis_labels(days)) <= 12
