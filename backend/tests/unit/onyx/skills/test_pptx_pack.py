"""Unpack -> edit -> pack round trips for the pptx skill's office scripts.

Each test drives the scripts the way the agent does: unpack.py into a directory,
edit the XML, then pack.py with --original so validation reports only errors the
edit introduced.
"""

import re
import subprocess
import sys
from pathlib import Path

import pptx
from pptx.util import Inches

SCRIPTS: Path = Path(__file__).parents[4] / "onyx/skills/builtin/pptx/scripts"
OFFICE: Path = SCRIPTS / "office"


def _build_deck(path: Path, text: str = "Quarterly results") -> None:
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text_frame.text = text
    prs.save(str(path))


def _run(script: Path, *args: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=script.parent,
        timeout=300,
    )


def _unpack(deck: Path, out: Path) -> Path:
    result = _run(OFFICE / "unpack.py", deck, out)
    assert result.returncode == 0, result.stdout + result.stderr
    return out / "ppt" / "slides" / "slide1.xml"


def _pack(
    unpacked: Path, out: Path, original: Path
) -> subprocess.CompletedProcess[str]:
    return _run(OFFICE / "pack.py", unpacked, out, "--original", original)


def _edit(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    edited = re.sub(pattern, replacement, text, count=1)
    assert edited != text, f"pattern {pattern!r} not found in {path.name}"
    path.write_text(edited, encoding="utf-8")


def test_external_link_does_not_block_pack(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    run = box.text_frame.paragraphs[0].add_run()
    run.text = "Source data"
    run.hyperlink.address = "file:///C:/Users/analyst/Q3%20figures.xlsx"
    prs.save(str(deck))

    unpacked = tmp_path / "unpacked"
    _unpack(deck, unpacked)
    result = _pack(unpacked, tmp_path / "out.pptx", deck)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "out.pptx").is_file()


def test_pack_leaves_drawingml_text_without_xml_space(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck, text=" leading and trailing ")

    unpacked = tmp_path / "unpacked"
    _unpack(deck, unpacked)
    out = tmp_path / "out.pptx"
    result = _pack(unpacked, out, deck)
    assert result.returncode == 0, result.stdout + result.stderr

    packed = pptx.Presentation(str(out))
    shape = packed.slides[0].shapes[0]
    assert shape.text_frame.text == " leading and trailing "
    assert "xml:space" not in shape.text_frame._txBody.xml


def test_slide_edit_that_breaks_the_schema_is_rejected(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)

    unpacked = tmp_path / "unpacked"
    slide = _unpack(deck, unpacked)
    # a:t is only valid inside a:r or a:fld, never directly inside a:p.
    _edit(slide, r"<a:p>", "<a:p><a:t>loose text</a:t>")
    result = _pack(unpacked, tmp_path / "out.pptx", deck)

    assert result.returncode != 0
    assert "ppt/slides/slide1.xml" in result.stdout
    assert not (tmp_path / "out.pptx").exists()


def test_xml_space_on_drawingml_text_is_rejected(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)

    unpacked = tmp_path / "unpacked"
    slide = _unpack(deck, unpacked)
    _edit(slide, r"<a:t>Quarterly", '<a:t xml:space="preserve"> Quarterly')
    result = _pack(unpacked, tmp_path / "out.pptx", deck)

    assert result.returncode != 0
    assert "space" in result.stdout


def test_malformed_bullet_size_is_rejected(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)

    unpacked = tmp_path / "unpacked"
    slide = _unpack(deck, unpacked)
    _edit(slide, r"<a:r>", '<a:pPr><a:buSzPct val="not-a-number"/></a:pPr><a:r>')
    result = _pack(unpacked, tmp_path / "out.pptx", deck)

    assert result.returncode != 0
    assert "not-a-number" in result.stdout


def test_valid_slide_edit_packs(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)

    unpacked = tmp_path / "unpacked"
    slide = _unpack(deck, unpacked)
    _edit(slide, r"Quarterly results", "Annual results")
    out = tmp_path / "out.pptx"
    result = _pack(unpacked, out, deck)

    assert result.returncode == 0, result.stdout + result.stderr
    assert pptx.Presentation(str(out)).slides[0].shapes[0].text == "Annual results"


def test_duplicating_a_slide_keeps_its_existing_schema_errors_allowed(
    tmp_path: Path,
) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)
    # Give the original slide a schema error real decks carry: a color value
    # outside the hex pattern. Duplicating it must not count as a new error.
    seeded = tmp_path / "seeded"
    _unpack(deck, seeded)
    _edit(
        seeded / "ppt" / "slides" / "slide1.xml",
        r"<a:r>",
        '<a:r><a:rPr lang="en-US"><a:solidFill><a:srgbClr val="GG0000"/>'
        "</a:solidFill></a:rPr>",
    )
    original = tmp_path / "original.pptx"
    seeded_pack = _run(OFFICE / "pack.py", seeded, original, "--validate", "false")
    assert seeded_pack.returncode == 0, seeded_pack.stdout + seeded_pack.stderr

    unpacked = tmp_path / "unpacked"
    _unpack(original, unpacked)
    added = _run(SCRIPTS / "add_slide.py", unpacked, "slide1.xml")
    assert added.returncode == 0, added.stdout + added.stderr
    sld_id = re.search(r"<p:sldId [^>]*/>", added.stdout)
    assert sld_id is not None, added.stdout
    _edit(
        unpacked / "ppt" / "presentation.xml",
        r"</p:sldIdLst>",
        sld_id.group(0) + "</p:sldIdLst>",
    )
    out = tmp_path / "out.pptx"
    result = _pack(unpacked, out, original)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(pptx.Presentation(str(out)).slides) == 2


def test_new_schema_error_on_a_duplicated_slide_is_rejected(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)

    unpacked = tmp_path / "unpacked"
    _unpack(deck, unpacked)
    added = _run(SCRIPTS / "add_slide.py", unpacked, "slide1.xml")
    assert added.returncode == 0, added.stdout + added.stderr
    sld_id = re.search(r"<p:sldId [^>]*/>", added.stdout)
    assert sld_id is not None, added.stdout
    _edit(
        unpacked / "ppt" / "presentation.xml",
        r"</p:sldIdLst>",
        sld_id.group(0) + "</p:sldIdLst>",
    )
    _edit(unpacked / "ppt" / "slides" / "slide2.xml", r"<a:p>", "<a:p><a:t>loose</a:t>")
    result = _pack(unpacked, tmp_path / "out.pptx", deck)

    assert result.returncode != 0
    assert "ppt/slides/slide2.xml" in result.stdout


def test_values_written_by_powerpoint_pack(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    _build_deck(deck)
    # PowerPoint writes buSzPct in thousandths of a percent and pitchFamily
    # values outside the schema's list; the bundled schema rejects both.
    # Changing the values must not fail validation.
    seeded = tmp_path / "seeded"
    _unpack(deck, seeded)
    _edit(
        seeded / "ppt" / "slides" / "slide1.xml",
        r"<a:r>",
        '<a:pPr><a:buSzPct val="70000"/></a:pPr><a:r><a:rPr lang="en-US">'
        '<a:latin typeface="Arial" pitchFamily="84"/></a:rPr>',
    )
    original = tmp_path / "original.pptx"
    seeded_pack = _run(OFFICE / "pack.py", seeded, original, "--validate", "false")
    assert seeded_pack.returncode == 0, seeded_pack.stdout + seeded_pack.stderr

    unpacked = tmp_path / "unpacked"
    slide = _unpack(original, unpacked)
    _edit(slide, r'val="70000"', 'val="80000"')
    _edit(slide, r'pitchFamily="84"', 'pitchFamily="85"')
    result = _pack(unpacked, tmp_path / "out.pptx", original)

    assert result.returncode == 0, result.stdout + result.stderr


def test_duplicate_that_reuses_a_deleted_slide_name_packs(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    prs = pptx.Presentation()
    for _ in range(2):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
        box.text_frame.text = "Quarterly results"
    prs.save(str(deck))
    # Slide 1 carries a schema error that the original deck already has.
    seeded = tmp_path / "seeded"
    _unpack(deck, seeded)
    _edit(
        seeded / "ppt" / "slides" / "slide1.xml",
        r"<a:r>",
        '<a:r><a:rPr lang="en-US"><a:solidFill><a:srgbClr val="GG0000"/>'
        "</a:solidFill></a:rPr>",
    )
    original = tmp_path / "original.pptx"
    seeded_pack = _run(OFFICE / "pack.py", seeded, original, "--validate", "false")
    assert seeded_pack.returncode == 0, seeded_pack.stdout + seeded_pack.stderr

    # Delete slide 2, then duplicate slide 1: the copy is named slide2.xml.
    unpacked = tmp_path / "unpacked"
    _unpack(original, unpacked)
    _edit(
        unpacked / "ppt" / "presentation.xml",
        r"<p:sldId [^>]*/>\s*</p:sldIdLst>",
        "</p:sldIdLst>",
    )
    cleaned = _run(SCRIPTS / "clean.py", unpacked)
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    added = _run(SCRIPTS / "add_slide.py", unpacked, "slide1.xml")
    assert added.returncode == 0, added.stdout + added.stderr
    assert (unpacked / "ppt" / "slides" / "slide2.xml").is_file()
    sld_id = re.search(r"<p:sldId [^>]*/>", added.stdout)
    assert sld_id is not None, added.stdout
    _edit(
        unpacked / "ppt" / "presentation.xml",
        r"</p:sldIdLst>",
        sld_id.group(0) + "</p:sldIdLst>",
    )
    result = _pack(unpacked, tmp_path / "out.pptx", original)

    assert result.returncode == 0, result.stdout + result.stderr
