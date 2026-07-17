"""Deterministic layout linter for PowerPoint files.

Statically checks a .pptx for mechanical layout defects that vision QA is
slow and unreliable at catching:

    BOUNDS    shape partially or fully off the slide canvas
    MARGIN    text content closer than the profile margin (0.5" standard /
              0.25" dense) to a slide edge
    OVERFLOW  estimated text height/width exceeds its box (PIL font metrics)
    OVERLAP   two text frames intersect, or text spills past its container
    CONTRAST  explicit text color vs. resolved solid background below WCAG-ish
              thresholds (image/theme backgrounds are skipped, not guessed)
    FONT      run font not in the sandbox's known-available set

Precision over recall: thresholds are lenient and intentional-overlap
patterns (text over pictures, shape-in-shape containment, full-bleed
backgrounds) are allowlisted. Rotated shapes and group internals are skipped
for geometric checks.

Output protocol (stdout):
    Line 1: status — LINT_CLEAN, LINT_ISSUES <n_errors> <n_warnings>, or ERROR_NOT_FOUND
    Lines 2+: one finding per line:
        slide N | shape "Name" (id=K) | SEVERITY CHECK | detail | text: "snippet"

Exit code: 1 if any ERROR finding, 0 otherwise (2 on usage error).

Usage:
    python lint.py /path/to/file.pptx [--profile {standard,dense}]
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont
from pptx import Presentation
from pptx.enum.dml import MSO_COLOR_TYPE
from pptx.enum.dml import MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.shapes.base import BaseShape
from pptx.util import Emu

EMU_PER_INCH = 914400
EMU_PER_PT = 12700

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
OVERFLOW_WARN_RATIO = 1.1  # est. content > 110% of box height
OVERFLOW_ERROR_RATIO = 1.35
OVERLAP_MIN_DIM_EMU = int(0.1 * EMU_PER_INCH)
OVERLAP_MIN_AREA_FRACTION = 0.15  # of the smaller shape
CONTAINER_SPILL_EMU = int(0.1 * EMU_PER_INCH)
CONTRAST_ERROR_RATIO = 2.5
CONTRAST_WARN_RATIO = 3.5  # slides are mostly large text; WCAG AA-large is 3:1
FOOTER_MAX_HEIGHT_EMU = int(0.4 * EMU_PER_INCH)
FOOTER_ZONE_FRACTION = 0.85  # shapes starting in the bottom 15% are footers
LINE_SPACING_FACTOR = 1.2
MEASURE_SCALE = 4  # render fonts at 4x pt size for sub-pixel width precision

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
    if getattr(shape, "has_text_frame", False):
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


# --- Font measurement -------------------------------------------------------

_font_file_cache: dict[tuple[str, bool], str | None] = {}
_font_cache: dict[tuple[str, bool, int], ImageFont.ImageFont] = {}
_HAS_FC_MATCH = shutil.which("fc-match") is not None


def _find_font_file(family: str, bold: bool) -> str | None:
    key = (family.lower(), bold)
    if key in _font_file_cache:
        return _font_file_cache[key]
    path: str | None = None
    if _HAS_FC_MATCH:
        pattern = f"{family}:weight={'bold' if bold else 'regular'}"
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", pattern],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            path = None
    _font_file_cache[key] = path
    return path


def _load_font(family: str, size_pt: float, bold: bool) -> ImageFont.ImageFont:
    px = max(int(round(size_pt * MEASURE_SCALE)), 4)
    key = (family.lower(), bold, px)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    font: ImageFont.ImageFont | None = None
    path = _find_font_file(family, bold)
    if path:
        try:
            font = ImageFont.truetype(path, px)
        except OSError:
            font = None
    if font is None:
        try:
            font = ImageFont.load_default(px)  # scalable since Pillow 10.1
        except TypeError:
            font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _text_width_pt(text: str, font: ImageFont.ImageFont, size_pt: float) -> float:
    try:
        return float(font.getlength(text)) / MEASURE_SCALE
    except AttributeError:
        # Bitmap fallback font: approximate with an average glyph width.
        return len(text) * size_pt * 0.55


# --- Paragraph layout estimation --------------------------------------------


def _run_size_pt(run, para) -> float | None:
    size = run.font.size
    if size is None:
        size = para.font.size
    return float(size.pt) if size is not None else None


def _para_font(para) -> tuple[str, float, bool] | None:
    """Dominant (family, size_pt, bold) for a paragraph.

    Returns None when no run carries an explicit size — inherited sizes
    (theme/master/layout) are not resolved, and guessing produces false
    overflow findings.
    """
    family = "Inter"
    size_pt = 0.0
    bold = False
    for run in para.runs:
        rs = _run_size_pt(run, para)
        if rs is not None and rs > size_pt:
            size_pt = rs
            family = run.font.name or para.font.name or family
            bold = bool(run.font.bold)
    if size_pt == 0.0:
        pf = para.font
        if pf.size is None:
            return None
        size_pt = float(pf.size.pt)
        family = pf.name or family
        bold = bool(pf.bold)
    return family, size_pt, bold


def _wrap_line_count(
    text: str, usable_w_pt: float, font: ImageFont.ImageFont, size_pt: float
) -> int:
    if not text.strip():
        return 1
    lines = 0
    space_w = _text_width_pt(" ", font, size_pt)
    # Hard line breaks (a:br) surface as "\v" in python-pptx paragraph text.
    for hard_line in text.replace("\v", "\n").split("\n"):
        lines += 1
        current = 0.0
        for word in hard_line.split():
            w = _text_width_pt(word, font, size_pt)
            # a single over-wide word char-wraps; don't explode
            w = min(w, usable_w_pt)
            if current > 0 and current + space_w + w > usable_w_pt:
                lines += 1
                current = w
            else:
                current = current + (space_w if current > 0 else 0.0) + w
    return lines


def _estimate_text_extent(shape, box: Box) -> tuple[float, float, float, float] | None:
    """Return (est_height_emu, avail_height_emu, max_line_w_pt, usable_w_pt).

    Returns None when any paragraph's font size can't be resolved from
    explicit run/paragraph properties — the estimate would be a guess.
    """
    tf = shape.text_frame
    usable_w_emu = box.width - int(tf.margin_left or 0) - int(tf.margin_right or 0)
    avail_h_emu = box.height - int(tf.margin_top or 0) - int(tf.margin_bottom or 0)
    usable_w_pt = max(usable_w_emu / EMU_PER_PT, 1.0)
    wrap = tf.word_wrap is not False  # None (inherit) treated as wrapping

    est_h_pt = 0.0
    max_line_w_pt = 0.0
    min_line_h_pt: float | None = None
    for para in tf.paragraphs:
        # para.text includes hard line breaks (a:br) as "\v", unlike para.runs.
        text = para.text
        if not text.strip():
            continue  # blank spacer paragraph at unknown size — ignore
        para_font = _para_font(para)
        if para_font is None:
            return None
        family, size_pt, bold = para_font
        font = _load_font(family, size_pt, bold)
        if wrap:
            lines = _wrap_line_count(text, usable_w_pt, font, size_pt)
        else:
            hard_lines = text.replace("\v", "\n").split("\n")
            lines = len(hard_lines)
            max_line_w_pt = max(
                max_line_w_pt,
                max(_text_width_pt(ln, font, size_pt) for ln in hard_lines),
            )
        line_h = size_pt * LINE_SPACING_FACTOR
        spacing = para.line_spacing
        if isinstance(spacing, float):
            line_h = size_pt * LINE_SPACING_FACTOR * spacing
        elif spacing is not None:  # Length
            line_h = float(spacing.pt)
        est_h_pt += lines * line_h
        min_line_h_pt = line_h if min_line_h_pt is None else min(min_line_h_pt, line_h)
        if para.space_before is not None:
            est_h_pt += float(para.space_before.pt)
        if para.space_after is not None:
            est_h_pt += float(para.space_after.pt)
    if min_line_h_pt is not None and avail_h_emu < 0.9 * min_line_h_pt * EMU_PER_PT:
        # Box can't even fit one line: an intentional anchor/label pattern
        # where text deliberately renders past the box, not a layout bug.
        return None
    return est_h_pt * EMU_PER_PT, float(avail_h_emu), max_line_w_pt, usable_w_pt


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
    try:
        fill = shape.fill
    except (AttributeError, TypeError, ValueError):
        return "unresolvable"  # groups etc. — children could paint anything
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


def check_overflow(slide_no: int, shapes: list[tuple[BaseShape, Box]]) -> list[Finding]:
    findings: list[Finding] = []
    for shape, box in shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        tf = shape.text_frame
        if not tf.text.strip():
            continue
        if tf.auto_size in (
            MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE,
            MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT,
        ):
            continue  # PowerPoint will shrink text / grow the box
        extent = _estimate_text_extent(shape, box)
        if extent is None:
            continue  # inherited font sizes — estimate would be a guess
        est_h, avail_h, max_line_w_pt, usable_w_pt = extent
        if avail_h <= 0:
            continue
        if tf.word_wrap is False:
            if max_line_w_pt > 1.1 * usable_w_pt:
                findings.append(
                    Finding(
                        slide_no,
                        shape.name,
                        shape.shape_id,
                        "WARN",
                        "OVERFLOW",
                        f"no-wrap text est. {max_line_w_pt:.0f}pt wide in "
                        f"{usable_w_pt:.0f}pt box",
                        tf.text,
                    )
                )
            continue
        ratio = est_h / avail_h
        if ratio <= OVERFLOW_WARN_RATIO:
            continue
        severity = "ERROR" if ratio > OVERFLOW_ERROR_RATIO else "WARN"
        findings.append(
            Finding(
                slide_no,
                shape.name,
                shape.shape_id,
                severity,
                "OVERFLOW",
                f'est. text height {est_h / EMU_PER_INCH:.2f}" in '
                f'{avail_h / EMU_PER_INCH:.2f}" box ({ratio:.0%})',
                tf.text,
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
        if not getattr(shape, "has_text_frame", False):
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
        if not getattr(shape, "has_text_frame", False):
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
            if not getattr(shape, "has_text_frame", False):
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
        findings.extend(check_overflow(slide_no, shapes))
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
