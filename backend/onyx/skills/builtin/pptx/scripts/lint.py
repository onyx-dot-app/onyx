"""Deterministic layout linter for PowerPoint files.

Statically checks a .pptx for mechanical layout defects that vision QA is
slow and unreliable at catching:

    BOUNDS    shape partially or fully off the slide canvas
    MARGIN    text content closer than the profile margin (0.5" standard /
              0.25" dense) to a slide edge
    OVERFLOW  text height/width exceeds its box (power-pptx text measurement,
              with sizes inherited from the layout, master, and theme)
    OVERLAP   two text frames intersect, or text spills past its container
    CONTRAST  explicit text color vs. resolved solid background below WCAG-ish
              thresholds (image/theme backgrounds are skipped, not guessed)
    FONT      run font not in the sandbox's known-available set

Precision over recall: thresholds are lenient and intentional-overlap
patterns (text over pictures, shape-in-shape containment, full-bleed
backgrounds) are allowlisted. Rotated shapes and group internals are skipped
for the geometric checks other than OVERFLOW, which measures every text frame.

Output protocol (stdout):
    Line 1: status — LINT_CLEAN, LINT_ISSUES <n_errors> <n_warnings>, ERROR_NOT_FOUND,
            or ERROR_MISSING_DEPENDENCY <package> (line 2 gives the install command)
    Lines 2+: one finding per line:
        slide N | shape "Name" (id=K) | SEVERITY CHECK | detail | text: "snippet"

Exit code: 1 if any ERROR finding, 0 otherwise (2 on usage error or a missing
dependency).

Usage:
    python lint.py /path/to/file.pptx [--profile {standard,dense}]
"""

import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from power_pptx import Presentation
    from power_pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL
    from power_pptx.enum.shapes import MSO_SHAPE_TYPE
    from power_pptx.enum.text import MSO_AUTO_SIZE
    from power_pptx.lint import TextOverflow, lint_slide
    from power_pptx.shapes.base import BaseShape
    from power_pptx.slide import Slide
    from power_pptx.text.fonts import find_font_file, register_font_family
    from power_pptx.util import Emu
except ModuleNotFoundError as e:
    if e.name != "power_pptx":
        raise
    # A sandbox started from an older image runs this script without power-pptx.
    print("ERROR_MISSING_DEPENDENCY power-pptx")
    print("Run `pip install power-pptx==2.15.0`, then run lint.py again.")
    sys.exit(2)

EMU_PER_INCH = 914400

# --- Thresholds (lenient by design) ---
MARGIN_MIN_EMU_BY_PROFILE = {
    "standard": int(0.45 * EMU_PER_INCH),  # nominal 0.5"
    "dense": int(0.22 * EMU_PER_INCH),  # nominal 0.25"
}
MARGIN_NOMINAL_IN_BY_PROFILE = {"standard": 0.5, "dense": 0.25}
DEFAULT_PROFILE = "standard"
FULL_BLEED_FRACTION = 0.9  # shape covering >=90% of a slide dimension is exempt
BOUNDS_OVERSHOOT_EMU = int(0.1 * EMU_PER_INCH)  # ignore bleed smaller than this
BOUNDS_ERROR_FRACTION = 0.35  # >35% of shape area off-slide is an ERROR
OVERFLOW_WARN_RATIO = 1.1  # measured text > 110% of the frame
OVERFLOW_ERROR_RATIO = 1.35
# Metric-compatible fonts the sandbox installs in place of Office fonts. Text is
# measured with the stand-in when the Office font itself is not installed.
METRIC_STAND_INS = {
    "Calibri": "Carlito",
    "Cambria": "Caladea",
    "Arial": "Liberation Sans",
    "Helvetica": "Liberation Sans",
    "Times New Roman": "Liberation Serif",
    "Courier New": "Liberation Mono",
}
# Every power-pptx lint rule except TextOverflow. Disabled rules are not run.
POWER_PPTX_OTHER_RULES = (
    "InvalidGeometry",
    "LayerOrderViolation",
    "LowContrast",
    "MasterPlaceholderCollision",
    "MinFontSize",
    "OffGridDrift",
    "OffSlide",
    "OffSlideShadow",
    "RaggedEdge",
    "ShapeCollision",
    "ShapeCollisionShadow",
    "ZOrderAnomaly",
)
OVERLAP_MIN_DIM_EMU = int(0.1 * EMU_PER_INCH)
OVERLAP_MIN_AREA_FRACTION = 0.15  # of the smaller shape
CONTAINER_SPILL_EMU = int(0.1 * EMU_PER_INCH)
CONTRAST_ERROR_RATIO = 2.5
CONTRAST_WARN_RATIO = 3.5  # slides are mostly large text; WCAG AA-large is 3:1
FOOTER_MAX_HEIGHT_EMU = int(0.4 * EMU_PER_INCH)
FOOTER_ZONE_FRACTION = 0.85  # shapes starting in the bottom 15% are footers

# Fonts installed (or metric-substituted) in the sandbox image, per SKILL.md.
KNOWN_FONTS = {
    "inter",
    "montserrat",
    "lato",
    "eb garamond",
    "fira code",
    "calibri",
    "cambria",
    "arial",
    "arial black",
    "times new roman",
    "liberation sans",
    "liberation serif",
    "liberation mono",
    "carlito",
    "caladea",
    "dejavu sans",
    "dejavu serif",
    "dejavu sans mono",
}

_NSMAP = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass
class Finding:
    slide: int  # 1-based
    shape_name: str
    shape_id: int
    severity: str  # ERROR | WARN
    check: str
    detail: str
    text: str = ""

    def render(self) -> str:
        line = (
            f'slide {self.slide} | shape "{self.shape_name}" (id={self.shape_id})'
            f" | {self.severity} {self.check} | {self.detail}"
        )
        if self.text:
            snippet = self.text.replace("\n", " ").strip()
            if len(snippet) > 40:
                snippet = snippet[:40] + "…"
            line += f' | text: "{snippet}"'
        return line


@dataclass
class Box:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def area(self) -> int:
        return max(self.width, 0) * max(self.height, 0)

    def intersect(self, other: "Box") -> "Box":
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return Box(left, top, max(right - left, 0), max(bottom - top, 0))

    def contains(self, other: "Box") -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def contains_point(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def _shape_box(shape) -> Box | None:
    try:
        left, top = shape.left, shape.top
        width, height = shape.width, shape.height
    except (AttributeError, TypeError, ValueError):
        return None
    if None in (left, top, width, height):
        return None
    return Box(int(left), int(top), int(width), int(height))


def _is_rotated(shape) -> bool:
    try:
        return bool(shape.rotation) and abs(shape.rotation) % 360 > 1
    except (AttributeError, TypeError, ValueError):
        return False


def _shape_text(shape) -> str:
    if getattr(shape, "has_text_frame", False):  # ods: ignore[getattr]
        return shape.text_frame.text
    return ""


def _is_full_bleed(box: Box, slide_w: int, slide_h: int) -> bool:
    # A shape only counts as a full-bleed background if it actually covers the
    # slide — full-bleed dimensions with most of the area off-slide don't qualify.
    clipped = box.intersect(Box(0, 0, slide_w, slide_h))
    return (
        box.width >= FULL_BLEED_FRACTION * slide_w
        and box.height >= FULL_BLEED_FRACTION * slide_h
        and box.area > 0
        and clipped.area >= FULL_BLEED_FRACTION * box.area
    )


def _is_picture(shape) -> bool:
    return shape.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.LINKED_PICTURE)


def _is_line(shape) -> bool:
    return shape.shape_type == MSO_SHAPE_TYPE.LINE


# --- Color / contrast helpers ------------------------------------------------


def _rel_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _rel_luminance(a), _rel_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _solid_fill_rgb(shape) -> tuple[int, int, int] | None:
    try:
        fill = shape.fill
        if fill.type != MSO_FILL.SOLID:
            return None
        color = fill.fore_color
        if color.type != MSO_COLOR_TYPE.RGB:
            return None
        rgb = color.rgb
        return (rgb[0], rgb[1], rgb[2])
    except (AttributeError, TypeError, ValueError):
        return None


def _fill_state(shape) -> str:
    """Classify a shape's fill: "solid_rgb", "none", or "unresolvable"."""
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return "unresolvable"  # children could paint anything
    try:
        fill = shape.fill
    except (AttributeError, TypeError, ValueError):
        return "unresolvable"
    try:
        fill_type = fill.type
    except (AttributeError, TypeError, ValueError):
        return "unresolvable"
    if fill_type in (None, MSO_FILL.BACKGROUND):
        return "none"
    if fill_type == MSO_FILL.SOLID:
        try:
            if fill.fore_color.type == MSO_COLOR_TYPE.RGB:
                return "solid_rgb"
        except (AttributeError, TypeError, ValueError):
            pass
        return "unresolvable"  # theme-colored solid — not resolved here
    return "unresolvable"  # gradient / pattern / picture fill


def _slide_background_rgb(slide) -> tuple[int, int, int] | None:
    try:
        fill = slide.background.fill
        if fill.type != MSO_FILL.SOLID:
            return None
        color = fill.fore_color
        if color.type != MSO_COLOR_TYPE.RGB:
            return None
        rgb = color.rgb
        return (rgb[0], rgb[1], rgb[2])
    except (AttributeError, TypeError, ValueError):
        return None


def _run_rgb(run) -> tuple[int, int, int] | None:
    try:
        color = run.font.color
        if color.type != MSO_COLOR_TYPE.RGB:
            return None
        rgb = color.rgb
        return (rgb[0], rgb[1], rgb[2])
    except (AttributeError, TypeError, ValueError):
        return None


# --- Checks -------------------------------------------------------------------


def check_bounds(
    slide_no: int, shapes: list[tuple[BaseShape, Box]], slide_w: int, slide_h: int
) -> list[Finding]:
    findings: list[Finding] = []
    slide_box = Box(0, 0, slide_w, slide_h)
    for shape, box in shapes:
        if _is_full_bleed(box, slide_w, slide_h):
            continue
        if box.area == 0:
            continue
        clipped = box.intersect(slide_box)
        outside_fraction = 1.0 - clipped.area / box.area
        if outside_fraction <= 0.0:
            continue
        overshoot = max(
            0 - box.left,
            0 - box.top,
            box.right - slide_w,
            box.bottom - slide_h,
        )
        if outside_fraction < 0.02 or overshoot <= BOUNDS_OVERSHOOT_EMU:
            continue
        is_content = bool(_shape_text(shape).strip()) or _is_picture(shape)
        if not is_content:
            # Decorative shapes (freeforms, groups, accent blobs) bleeding off
            # the edge is an intentional design technique — only flag when the
            # shape is mostly off-slide.
            if outside_fraction <= 0.5:
                continue
            severity = "WARN"
        else:
            severity = "ERROR" if outside_fraction > BOUNDS_ERROR_FRACTION else "WARN"
        findings.append(
            Finding(
                slide_no,
                shape.name,
                shape.shape_id,
                severity,
                "BOUNDS",
                f"{outside_fraction:.0%} of shape is off-slide "
                f'(overshoot {overshoot / EMU_PER_INCH:.2f}")',
                _shape_text(shape),
            )
        )
    return findings


def check_margins(
    slide_no: int,
    shapes: list[tuple[BaseShape, Box]],
    slide_w: int,
    slide_h: int,
    margin_min_emu: int,
    margin_nominal_in: float,
) -> list[Finding]:
    findings: list[Finding] = []
    for shape, box in shapes:
        text = _shape_text(shape).strip()
        if not text:
            continue  # only text content; decorative shapes may touch edges
        if (
            box.height <= FOOTER_MAX_HEIGHT_EMU
            and box.top >= FOOTER_ZONE_FRACTION * slide_h
        ):
            continue  # footer strips (page numbers, dates) legitimately hug edges
        exempt_h = box.width >= FULL_BLEED_FRACTION * slide_w
        exempt_v = box.height >= FULL_BLEED_FRACTION * slide_h
        edges = {
            "left": box.left,
            "right": slide_w - box.right,
            "top": box.top,
            "bottom": slide_h - box.bottom,
        }
        bad = [
            (name, dist)
            for name, dist in edges.items()
            if 0 <= dist < margin_min_emu
            and not (exempt_h and name in ("left", "right"))
            and not (exempt_v and name in ("top", "bottom"))
        ]
        if bad:
            desc = ", ".join(f'{name} {dist / EMU_PER_INCH:.2f}"' for name, dist in bad)
            findings.append(
                Finding(
                    slide_no,
                    shape.name,
                    shape.shape_id,
                    "WARN",
                    "MARGIN",
                    f'text within {margin_nominal_in:g}" of slide edge ({desc})',
                    text,
                )
            )
    return findings


def check_overflow(slide_no: int, slide: Slide) -> list[Finding]:
    findings: list[Finding] = []
    try:
        report = lint_slide(slide, disable=POWER_PPTX_OTHER_RULES)
    except Exception as e:
        # Report the gap, so that a failed measurement never reads as clean.
        findings.append(
            Finding(
                slide_no,
                "",
                0,
                "WARN",
                "OVERFLOW",
                f"text was not measured ({e!r}); check this slide visually",
            )
        )
        return findings
    for issue in report.issues:
        if not isinstance(issue, TextOverflow) or issue.row is not None:
            continue
        # Only grow-to-fit frames are skipped: PowerPoint grows the box. A
        # shrink-to-fit frame is measured at its stored fontScale, because
        # PowerPoint opens the deck at that scale and shrinks the text again
        # only when the user edits it.
        if issue.auto_size == "SHAPE_TO_FIT_TEXT":
            continue
        if issue.ratio <= OVERFLOW_WARN_RATIO:
            continue
        shape = issue.shapes[0]
        severity = "ERROR" if issue.ratio > OVERFLOW_ERROR_RATIO else "WARN"
        if issue.dimension == "width":
            detail = f"no-wrap text needs {issue.ratio:.0%} of the box width"
        else:
            detail = (
                f"text needs {issue.ratio:.0%} of the box height "
                f"({issue.overflow_pt:.0f}pt too tall)"
            )
        if issue.estimated:
            detail += ", estimated with fallback metrics for a missing font"
        findings.append(
            Finding(
                slide_no,
                shape.name,
                shape.shape_id,
                severity,
                "OVERFLOW",
                detail,
                shape.text_frame.text,
            )
        )
    return findings


def check_overlap(
    slide_no: int, shapes: list[tuple[BaseShape, Box]], slide_w: int, slide_h: int
) -> list[Finding]:
    findings: list[Finding] = []
    slide_area = slide_w * slide_h

    def _box_is_authoritative(shape) -> bool:
        # spAutoFit boxes get resized by PowerPoint at render time; the stored
        # bbox routinely overhangs the actual text and yields false overlaps.
        if not getattr(shape, "has_text_frame", False):  # ods: ignore[getattr]
            return True
        return shape.text_frame.auto_size != MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT

    text_shapes = [
        (i, shape, box)
        for i, (shape, box) in enumerate(shapes)
        if _shape_text(shape).strip()
        and not _is_full_bleed(box, slide_w, slide_h)
        and _box_is_authoritative(shape)
    ]

    # Text frame on text frame (partial intersection only; containment allowed).
    for a in range(len(text_shapes)):
        for b in range(a + 1, len(text_shapes)):
            _, shape_a, box_a = text_shapes[a]
            _, shape_b, box_b = text_shapes[b]
            if box_a.contains(box_b) or box_b.contains(box_a):
                continue
            inter = box_a.intersect(box_b)
            if inter.width < OVERLAP_MIN_DIM_EMU or inter.height < OVERLAP_MIN_DIM_EMU:
                continue
            smaller_area = min(box_a.area, box_b.area)
            if (
                smaller_area == 0
                or inter.area < OVERLAP_MIN_AREA_FRACTION * smaller_area
            ):
                continue
            findings.append(
                Finding(
                    slide_no,
                    shape_a.name,
                    shape_a.shape_id,
                    "ERROR",
                    "OVERLAP",
                    f'text frames intersect: overlaps shape "{shape_b.name}" '
                    f"(id={shape_b.shape_id}) by "
                    f'{inter.width / EMU_PER_INCH:.2f}" x '
                    f'{inter.height / EMU_PER_INCH:.2f}"',
                    _shape_text(shape_a),
                )
            )

    # Text spilling past a smaller container shape it sits on (card pattern).
    for _, text_shape, text_box in text_shapes:
        cx = text_box.left + text_box.width / 2
        cy = text_box.top + text_box.height / 2
        for container, cbox in shapes:
            if container is text_shape:
                continue
            if _is_picture(container) or _is_line(container):
                continue
            if _shape_text(container).strip():
                continue  # text-on-text handled above
            if cbox.area == 0 or cbox.area > 0.5 * slide_area:
                continue  # background-sized shapes are fine to overhang
            if not cbox.contains_point(cx, cy):
                continue
            if cbox.contains(text_box):
                continue
            spill = max(
                cbox.left - text_box.left,
                cbox.top - text_box.top,
                text_box.right - cbox.right,
                text_box.bottom - cbox.bottom,
            )
            if spill <= CONTAINER_SPILL_EMU:
                continue
            findings.append(
                Finding(
                    slide_no,
                    text_shape.name,
                    text_shape.shape_id,
                    "WARN",
                    "OVERLAP",
                    f'text extends {spill / EMU_PER_INCH:.2f}" beyond container '
                    f'shape "{container.name}" (id={container.shape_id})',
                    _shape_text(text_shape),
                )
            )
    return findings


def check_contrast(
    slide_no: int, slide, shapes: list[tuple[BaseShape, Box]]
) -> tuple[list[Finding], int]:
    """Returns (findings, skipped_run_count)."""
    findings: list[Finding] = []
    skipped = 0
    slide_bg = _slide_background_rgb(slide)

    for idx, (shape, box) in enumerate(shapes):
        if not getattr(shape, "has_text_frame", False):  # ods: ignore[getattr]
            continue
        if not shape.text_frame.text.strip():
            continue
        # Resolve the effective solid background behind this shape by walking
        # down the z-order. Stop at the first shape that visibly paints under
        # the text: solid RGB fill → usable; picture / gradient / theme /
        # group → unresolvable (skip, never guess past it); no fill → keep
        # walking.
        bg: tuple[int, int, int] | None = None
        unresolvable = False
        cx = box.left + box.width / 2
        cy = box.top + box.height / 2
        for j in range(idx, -1, -1):  # include the shape's own fill first
            other, obox = shapes[j]
            if other is not shape and not obox.contains_point(cx, cy):
                continue
            if _is_picture(other):
                unresolvable = True
                break
            fill_state = _fill_state(other)
            if fill_state == "none":
                continue
            if fill_state == "unresolvable":
                unresolvable = True
                break
            bg = _solid_fill_rgb(other)
            break
        if bg is None and not unresolvable:
            bg = slide_bg

        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if not run.text.strip():
                    continue
                fg = _run_rgb(run)
                if fg is None:
                    continue  # theme/inherited color — out of scope
                if bg is None:
                    skipped += 1
                    continue
                ratio = _contrast_ratio(fg, bg)
                if ratio >= CONTRAST_WARN_RATIO:
                    continue
                severity = "ERROR" if ratio < CONTRAST_ERROR_RATIO else "WARN"
                findings.append(
                    Finding(
                        slide_no,
                        shape.name,
                        shape.shape_id,
                        severity,
                        "CONTRAST",
                        f"contrast {ratio:.1f}:1 "
                        f"(text #{fg[0]:02X}{fg[1]:02X}{fg[2]:02X} on "
                        f"#{bg[0]:02X}{bg[1]:02X}{bg[2]:02X})",
                        run.text,
                    )
                )
    return findings, skipped


def _embedded_font_names(prs) -> set[str]:
    try:
        elements = prs.part._element.findall(
            "p:embeddedFontLst/p:embeddedFont/p:font", _NSMAP
        )
        return {e.get("typeface", "").lower() for e in elements if e.get("typeface")}
    except (AttributeError, ValueError):
        return set()


def check_fonts(prs) -> list[Finding]:
    available = KNOWN_FONTS | _embedded_font_names(prs)
    findings: list[Finding] = []
    seen: set[str] = set()
    for slide_no, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):  # ods: ignore[getattr]
                continue
            for para in shape.text_frame.paragraphs:
                names = [para.font.name] + [run.font.name for run in para.runs]
                for name in names:
                    if not name or name.startswith("+"):
                        continue  # theme font references resolve fine
                    if name.lower() in available or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    findings.append(
                        Finding(
                            slide_no,
                            shape.name,
                            shape.shape_id,
                            "WARN",
                            "FONT",
                            f'font "{name}" is not installed in the sandbox — '
                            "it will silently render as a fallback font",
                        )
                    )
    return findings


# --- Driver -------------------------------------------------------------------


def lint_presentation(prs, profile: str = DEFAULT_PROFILE) -> tuple[list[Finding], int]:
    """Lint an open Presentation. Returns (findings, contrast_skipped_runs)."""
    if profile not in MARGIN_MIN_EMU_BY_PROFILE:
        valid = ", ".join(sorted(MARGIN_MIN_EMU_BY_PROFILE))
        raise ValueError(f"unknown profile {profile!r}; valid profiles: {valid}")
    margin_min_emu = MARGIN_MIN_EMU_BY_PROFILE[profile]
    margin_nominal_in = MARGIN_NOMINAL_IN_BY_PROFILE[profile]
    slide_w = int(prs.slide_width or Emu(int(10 * EMU_PER_INCH)))
    slide_h = int(prs.slide_height or Emu(int(7.5 * EMU_PER_INCH)))

    # Registering a family clears power-pptx's font index, so look every
    # file up before registering any.
    stand_in_files = {
        office_font: [
            find_font_file(stand_in, bold=bold, italic=italic)
            for bold, italic in (
                (False, False),
                (True, False),
                (False, True),
                (True, True),
            )
        ]
        for office_font, stand_in in METRIC_STAND_INS.items()
        if find_font_file(office_font) is None
    }
    for office_font, (regular, bold, italic, bold_italic) in stand_in_files.items():
        if regular:
            register_font_family(
                office_font,
                regular=regular,
                bold=bold,
                italic=italic,
                bold_italic=bold_italic,
            )
    findings: list[Finding] = []
    total_skipped = 0
    for slide_no, slide in enumerate(prs.slides, start=1):
        shapes: list[tuple[BaseShape, Box]] = []
        for shape in slide.shapes:
            box = _shape_box(shape)
            if box is None or _is_rotated(shape):
                continue
            shapes.append((shape, box))

        findings.extend(check_bounds(slide_no, shapes, slide_w, slide_h))
        findings.extend(
            check_margins(
                slide_no, shapes, slide_w, slide_h, margin_min_emu, margin_nominal_in
            )
        )
        findings.extend(check_overflow(slide_no, slide))
        findings.extend(check_overlap(slide_no, shapes, slide_w, slide_h))
        contrast_findings, skipped = check_contrast(slide_no, slide, shapes)
        findings.extend(contrast_findings)
        total_skipped += skipped

    findings.extend(check_fonts(prs))
    findings.sort(key=lambda f: (f.slide, 0 if f.severity == "ERROR" else 1, f.check))
    return findings, total_skipped


def lint_file(path: Path, profile: str = DEFAULT_PROFILE) -> tuple[list[Finding], int]:
    return lint_presentation(Presentation(str(path)), profile=profile)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Lint a .pptx for layout defects.")
    parser.add_argument("pptx_path", type=Path)
    parser.add_argument(
        "--profile",
        choices=sorted(MARGIN_MIN_EMU_BY_PROFILE),
        default=DEFAULT_PROFILE,
        help="Density profile: 'standard' (0.5\" margins) or 'dense' (0.25\", "
        "for intentionally content-dense analytical/consulting decks). Only the "
        "MARGIN warning threshold changes; error-level checks are unaffected.",
    )
    args = parser.parse_args()

    pptx_path = args.pptx_path
    if not pptx_path.is_file():
        print("ERROR_NOT_FOUND")
        sys.exit(1)

    findings, contrast_skipped = lint_file(pptx_path, profile=args.profile)
    errors = sum(1 for f in findings if f.severity == "ERROR")
    warnings = sum(1 for f in findings if f.severity == "WARN")

    if not findings:
        print("LINT_CLEAN")
    else:
        print(f"LINT_ISSUES {errors} {warnings}")
        for finding in findings:
            print(finding.render())
    if contrast_skipped:
        print(
            f"note: contrast skipped for {contrast_skipped} run(s) over "
            "image/unresolvable backgrounds — verify those visually",
            file=sys.stderr,
        )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
