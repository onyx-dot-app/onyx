"""Renders the usage report review pack as a PDF.

The `ty: ignore`s below are load-bearing: ReportLab types `chart.data` from a
sample literal and populates `valueAxis.labels` dynamically, so neither is
resolvable by a static checker.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ee.onyx.server.reporting.usage_report_branding import ReportBranding
from ee.onyx.server.reporting.usage_report_data import (
    DORMANT_USER_LIMIT,
    NamedSpend,
    UsageReportData,
)
from onyx.configs.constants import DANSWER_API_KEY_PREFIX, UNNAMED_KEY_PLACEHOLDER
from onyx.db.api_key import is_api_key_email_address
from onyx.utils.logger import setup_logger

logger = setup_logger()

_INK = colors.HexColor("#1c1c1c")  # onyx-ink-95
_ACCENT = colors.HexColor("#286df8")  # action-selection-05 / blue-50
_BODY = colors.HexColor("#54545d")  # stone-60, 7.5:1 on white
_HAIRLINE = colors.HexColor("#e6e6e9")  # stone-10
_SURFACE = colors.HexColor("#f0f0f1")  # stone-05

_CONTENT_WIDTH = LETTER[0] - 2 * inch
_MAX_AXIS_LABELS = 12
_LOGO_MAX_W, _LOGO_MAX_H = 2.0 * inch, 0.5 * inch


def _dollars(cents: float) -> str:
    return f"${cents / 100:,.2f}"


def _thousands(value: int) -> str:
    return f"{value:,}"


def _display_name(name: str) -> str:
    """Render an API key by its name instead of its synthetic address.

    Each API key owns a `User` row whose email is
    `API_KEY__<key name>@<uuid>onyxapikey.ai`, so per-key spend already
    aggregates correctly. Only the label needs help. A no-op for every other
    name, since none of them carry the API-key domain.
    """
    if not is_api_key_email_address(name):
        return name

    # The key's name can itself contain "@", so split on the last one.
    local_part = name.rsplit("@", 1)[0]
    # Stored emails are lowercased by a DB check constraint, so the prefix
    # cannot be matched case-sensitively against the constant.
    if local_part.lower().startswith(DANSWER_API_KEY_PREFIX.lower()):
        local_part = local_part[len(DANSWER_API_KEY_PREFIX) :]
    return f"{local_part or UNNAMED_KEY_PLACEHOLDER} (API key)"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=32,
            leading=36,
            textColor=_INK,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "wordmark": ParagraphStyle(
            "Wordmark",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            textColor=_INK,
        ),
        "cover_period": ParagraphStyle(
            "CoverPeriod",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=13,
            leading=18,
            textColor=_BODY,
        ),
        "lede": ParagraphStyle(
            "Lede",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11.5,
            leading=17,
            textColor=_INK,
        ),
        "heading": ParagraphStyle(
            "Heading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=_INK,
            spaceBefore=22,
            spaceAfter=2,
            keepWithNext=1,
        ),
        "subheading": ParagraphStyle(
            "Subheading",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=_BODY,
            spaceAfter=10,
            keepWithNext=1,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=_BODY,
            spaceBefore=4,
        ),
    }


def _logo_flowable(branding: ReportBranding) -> Flowable | None:
    if not branding.logo:
        return None
    try:
        reader = ImageReader(BytesIO(branding.logo))
        src_w, src_h = reader.getSize()
    except Exception:
        logger.exception(
            "Usage report could not render the configured logo for %s",
            branding.application_name,
        )
        return None
    if not src_w or not src_h:
        return None

    scale = min(_LOGO_MAX_W / src_w, _LOGO_MAX_H / src_h)
    return Image(
        BytesIO(branding.logo), width=src_w * scale, height=src_h * scale, mask="auto"
    )


class _NumberedCanvas(canvas.Canvas):
    """Stamps "page N of M" once the total is known.

    The total only exists after the last page is laid out, so pages are held
    back until save. The cover is deliberately left unnumbered.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, object]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for number, state in enumerate(self._pages, start=1):
            self.__dict__.update(state)
            if number > 1:
                self._draw_folio(number, total)
            super().showPage()
        super().save()

    def _draw_folio(self, number: int, total: int) -> None:
        width = self._pagesize[0]
        self.setFont("Helvetica", 8.5)
        self.setFillColor(_BODY)
        self.drawRightString(width - inch, 0.6 * inch, f"{number} of {total}")


class _Rule(Flowable):
    def __init__(self, width: float, color: colors.Color = _HAIRLINE) -> None:
        super().__init__()
        self.width, self.height, self.color = width, 1, color

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(1)
        self.canv.line(0, 0, self.width, 0)


class _SeatMeter(Flowable):
    """Seats in use against seats bought."""

    def __init__(self, active: int, licensed: int, unseated: int, width: float) -> None:
        super().__init__()
        self.active, self.licensed, self.unseated = active, licensed, unseated
        self.width, self.height = width, 54

    def draw(self) -> None:
        c = self.canv
        bar_h, bar_y = 14, 20
        ratio = min(1.0, self.active / self.licensed) if self.licensed else 0.0

        c.setFillColor(_SURFACE)
        c.roundRect(0, bar_y, self.width, bar_h, 3, stroke=0, fill=1)
        if ratio > 0:
            c.setFillColor(_ACCENT)
            c.roundRect(
                0, bar_y, max(3.0, self.width * ratio), bar_h, 3, stroke=0, fill=1
            )

        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(
            0, bar_y + bar_h + 8, f"{self.active} of {self.licensed} seats active"
        )

        c.setFillColor(_BODY)
        c.setFont("Helvetica", 9)
        idle = self.licensed - self.active
        caption = (
            f"{ratio:.0%} in use · {idle} seats idle"
            if idle
            else f"{ratio:.0%} of licensed seats in use"
        )
        if self.unseated:
            caption += f" · {self.unseated} used it without a seat"
        c.drawString(0, bar_y - 13, caption)


def _headline(data: UsageReportData) -> Table:
    figures = [
        (_thousands(data.active_users), "People using it"),
        (_dollars(data.total_cost_cents), "Total spend"),
        (_dollars(data.cost_per_active_user_cents), "Cost per active person"),
    ]
    value_style = ParagraphStyle(
        "Figure",
        fontName="Helvetica-Bold",
        fontSize=23,
        leading=26,
        textColor=_INK,
    )
    label_style = ParagraphStyle(
        "FigureLabel",
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=_BODY,
    )
    row = [
        [Paragraph(v, value_style) for v, _ in figures],
        [Paragraph(label, label_style) for _, label in figures],
    ]
    col = _CONTENT_WIDTH / 3
    table = Table(row, colWidths=[col] * 3, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def _table(rows: list[list[str]], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), _INK),
                ("TEXTCOLOR", (0, 1), (-1, -1), _BODY),
                ("TEXTCOLOR", (0, 1), (0, -1), _INK),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("LINEBELOW", (0, 0), (-1, 0), 1, _INK),
                ("LINEBELOW", (0, 1), (-1, -2), 0.5, _HAIRLINE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _axis_labels(days: list[str]) -> list[str]:
    """Keep at most `_MAX_AXIS_LABELS` ticks, blanking the rest."""
    step = max(1, (len(days) + _MAX_AXIS_LABELS - 1) // _MAX_AXIS_LABELS)
    # Drop the year: the period is already stated on the cover.
    return [day[5:] if index % step == 0 else "" for index, day in enumerate(days)]


def _style_axes(chart: HorizontalLineChart | VerticalBarChart) -> None:
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = _BODY
    chart.categoryAxis.strokeColor = _HAIRLINE
    chart.valueAxis.labels.fontName = "Helvetica"  # ty: ignore[unresolved-attribute]
    chart.valueAxis.labels.fontSize = 7  # ty: ignore[unresolved-attribute]
    chart.valueAxis.labels.fillColor = _BODY  # ty: ignore[unresolved-attribute]
    chart.valueAxis.strokeColor = _HAIRLINE
    chart.valueAxis.valueMin = 0
    chart.valueAxis.gridStrokeColor = _HAIRLINE
    chart.valueAxis.gridStrokeWidth = 0.5
    chart.valueAxis.visibleGrid = True


def _spend_over_time(data: UsageReportData) -> Drawing:
    drawing = Drawing(_CONTENT_WIDTH, 168)
    chart = HorizontalLineChart()
    chart.x, chart.y = 42, 28
    chart.width, chart.height = int(_CONTENT_WIDTH - 56), 122
    chart.data = [[point.cost_cents / 100 for point in data.daily]]  # ty: ignore[invalid-assignment]
    chart.categoryAxis.categoryNames = _axis_labels([p.day for p in data.daily])
    _style_axes(chart)
    chart.lines[0].strokeColor = _ACCENT
    chart.lines[0].strokeWidth = 1.6
    drawing.add(chart)
    return drawing


def _active_users_over_time(data: UsageReportData) -> Drawing:
    drawing = Drawing(_CONTENT_WIDTH, 168)
    chart = HorizontalLineChart()
    chart.x, chart.y = 42, 28
    chart.width, chart.height = int(_CONTENT_WIDTH - 56), 122
    chart.data = [[float(point.active_users) for point in data.daily]]  # ty: ignore[invalid-assignment]
    chart.categoryAxis.categoryNames = _axis_labels([p.day for p in data.daily])
    _style_axes(chart)
    chart.lines[0].strokeColor = _INK
    chart.lines[0].strokeWidth = 1.6
    drawing.add(chart)
    return drawing


def _spend_by_model(data: UsageReportData) -> Drawing:
    drawing = Drawing(_CONTENT_WIDTH, 170)
    chart = VerticalBarChart()
    chart.x, chart.y = 42, 38
    chart.width, chart.height = int(_CONTENT_WIDTH - 56), 112
    chart.data = [[entry.cost_cents / 100 for entry in data.by_model]]  # ty: ignore[invalid-assignment]
    chart.categoryAxis.categoryNames = [
        _display_name(entry.name) for entry in data.by_model
    ]
    _style_axes(chart)
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -8
    chart.bars[0].fillColor = _ACCENT
    chart.bars[0].strokeColor = None
    chart.barSpacing = 2
    drawing.add(chart)
    return drawing


def _cover(
    data: UsageReportData,
    branding: ReportBranding,
    styles: dict[str, ParagraphStyle],
) -> list[Flowable]:
    period = (
        f"{data.period_start.date().isoformat()} to "
        f"{data.period_end.date().isoformat()} (UTC)"
    )
    story: list[Flowable] = []

    logo = _logo_flowable(branding)
    if logo is not None:
        logo.hAlign = "LEFT"
        story += [logo, Spacer(1, 30)]
    else:
        story += [
            Paragraph(escape(branding.application_name), styles["wordmark"]),
            Spacer(1, 26),
        ]

    story += [
        Paragraph("Usage report", styles["cover_title"]),
        Paragraph(period, styles["cover_period"]),
        Spacer(1, 26),
        _Rule(_CONTENT_WIDTH, _INK),
        Spacer(1, 22),
        _headline(data),
        Spacer(1, 30),
    ]

    if data.licensed_users:
        story += [
            _SeatMeter(
                data.seated_active_users,
                data.licensed_users,
                data.active_users - data.seated_active_users,
                _CONTENT_WIDTH,
            )
        ]

    story += [
        Spacer(1, 30),
        Paragraph(_summary_sentence(data, branding.application_name), styles["lede"]),
    ]

    if data.by_model:
        story += [
            Spacer(1, 26),
            Paragraph("Top models by spend", styles["subheading"]),
            _spend_table("Model", data.by_model[:3]),
        ]

    return story


def _summary_sentence(data: UsageReportData, application_name: str) -> str:
    """Returns Paragraph markup, so every interpolated name is escaped."""
    people = "1 person" if data.active_users == 1 else f"{data.active_users} people"
    parts = [
        f"{people} used {escape(application_name)} in this period, at a total cost "
        f"of {_dollars(data.total_cost_cents)}."
    ]
    if data.by_flow:
        flow = escape(_display_name(data.by_flow[0].name))
        parts.append(f"Most of that ran through {flow}.")
    if data.dormant_user_count:
        share = (
            data.dormant_user_count / data.licensed_users
            if data.licensed_users
            else 0.0
        )
        parts.append(
            f"{data.dormant_user_count} of {data.licensed_users} licensed seats "
            f"({share:.0%}) went unused and are candidates to reassign."
        )
    return " ".join(parts)


def _spend_table(label: str, entries: list[NamedSpend]) -> Table:
    rows: list[list[str]] = [[label, "Spend (USD)", "Tokens"]]
    rows += [
        [
            _display_name(entry.name),
            _dollars(entry.cost_cents),
            _thousands(entry.total_tokens),
        ]
        for entry in entries
    ]
    widths = [_CONTENT_WIDTH * 0.5, _CONTENT_WIDTH * 0.25, _CONTENT_WIDTH * 0.25]
    return _table(rows, widths)


def _section(
    heading: str, subheading: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    return [
        Paragraph(heading, styles["heading"]),
        Paragraph(subheading, styles["subheading"]),
    ]


def _charted_section(
    heading: str,
    subheading: str,
    chart: Drawing,
    styles: dict[str, ParagraphStyle],
) -> Flowable:
    """`keepWithNext` does not reach into a KeepTogether, so the heading must
    travel inside the group or it strands at the page foot."""
    return KeepTogether(
        [
            Paragraph(heading, styles["heading"]),
            Paragraph(subheading, styles["subheading"]),
            chart,
        ]
    )


def render_usage_report_pdf(data: UsageReportData, branding: ReportBranding) -> bytes:
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=f"{branding.application_name} usage report",
        author=branding.application_name,
        # Byte-identical output for identical input.
        invariant=1,
    )

    story: list[Flowable] = []

    if not data.has_usage:
        logo = _logo_flowable(branding)
        if logo is not None:
            logo.hAlign = "LEFT"
            story += [logo, Spacer(1, 30)]
        else:
            story += [
                Paragraph(escape(branding.application_name), styles["wordmark"]),
                Spacer(1, 26),
            ]
        story += [
            Paragraph("Usage report", styles["cover_title"]),
            Paragraph(
                f"{data.period_start.date().isoformat()} to "
                f"{data.period_end.date().isoformat()} (UTC)",
                styles["cover_period"],
            ),
            Spacer(1, 24),
            Paragraph(
                "No recorded usage in this period. If the deployment was active, "
                "the usage rollup may have started after the period began.",
                styles["lede"],
            ),
        ]
        doc.build(story, canvasmaker=_NumberedCanvas)
        return buffer.getvalue()

    story += _cover(data, branding, styles)
    story += [PageBreak()]

    story += [
        _charted_section(
            "Adoption",
            "Distinct people who sent at least one message each day.",
            _active_users_over_time(data),
            styles,
        ),
        _charted_section(
            "Spend over time",
            "Daily cost across every model and surface.",
            _spend_over_time(data),
            styles,
        ),
        _charted_section(
            "Where the spend goes",
            "Cost by model for the period.",
            _spend_by_model(data),
            styles,
        ),
        Spacer(1, 6),
        _spend_table("Model", data.by_model),
    ]

    story += _section("Heaviest users", "The people driving most of the cost.", styles)
    story += [_spend_table("User", data.top_users)]

    story += _section("Spend by surface", "Where the work happens.", styles)
    story += [_spend_table("Flow", data.by_flow)]

    story += _section(
        "Seats not in use",
        "Licensed people who sent nothing this period. Reclaim, retrain, or "
        "drop them at renewal.",
        styles,
    )
    if not data.dormant_users:
        story.append(
            Paragraph("Every licensed seat was used this period.", styles["lede"])
        )
    else:
        shown = data.dormant_users[:DORMANT_USER_LIMIT]
        rows: list[list[str]] = [["User"]] + [[email] for email in shown]
        story.append(_table(rows, [_CONTENT_WIDTH]))
        remaining = data.dormant_user_count - len(shown)
        if remaining > 0:
            story.append(
                Paragraph(
                    f"{remaining} more idle seats. See users.csv for the full list.",
                    styles["note"],
                )
            )

    story += [
        Spacer(1, 20),
        _Rule(_CONTENT_WIDTH),
        Spacer(1, 8),
        Paragraph(
            "Spend from deleted users and API keys is included in every total "
            "and attributed separately. Neither counts as a person or a seat. "
            "Days are UTC.",
            styles["note"],
        ),
    ]

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
