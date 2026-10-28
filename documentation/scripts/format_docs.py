#!/usr/bin/env python3
"""
Repo-wide formatter for Markdown/MDX docs.

Enforces:
- Indentation: convert tabs to four spaces outside code blocks; list indents normalized to multiples of four.
- Newlines: ensure a single blank line before and after headings, images, and MDX components like Step/Accordion.
- Wrapping: wrap plain text lines to 120 chars (skips code blocks and risky lines).

Usage:
  python scripts/format_docs.py --check   # show files that would change
  python scripts/format_docs.py --write   # rewrite files in-place
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import re
import sys
from typing import List


INDENT_SPACES = 2


MD_EXTS = {".md", ".mdx", ".markdown"}


def iter_doc_files(root: str) -> List[str]:
    files: List[str] = []
    for base, _dirs, fnames in os.walk(root):
        # Skip common build/output dirs if present
        parts = set(base.split(os.sep))
        if {"node_modules", ".git", ".next", "dist", "build", "archive"} & parts:
            continue
        for fn in fnames:
            _, ext = os.path.splitext(fn)
            if ext.lower() in MD_EXTS:
                files.append(os.path.join(base, fn))
    return files


FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6} \S")
HR_RE = re.compile(r"^\s{0,3}(-{3,}|_{3,}|\*{3,})\s*$")
IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)")
LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>(?:[-+*]|\d+[.)]))\s+")
TABLE_RE = re.compile(r"\|.*\|")
BAD_NUM_LIST_RE = re.compile(r"^\s*\d+[.)](\S)")  # missing space after 1. or 1)
ANY_NUM_LIST_RE = re.compile(r"^\s*\d+[.)](?:\s|$)")  # any numbered list marker


BLOCK_COMPONENT_PREFIXES = (
    # Container-level components that should be surrounded by blank lines
    "<Steps",
    "</Steps",
    "<Accordion",
    "</Accordion",
    "<Image",
)


def is_code_fence(line: str) -> bool:
    return bool(FENCE_RE.match(line))


def is_heading(line: str) -> bool:
    return bool(HEADING_RE.match(line))


def is_hr(line: str) -> bool:
    return bool(HR_RE.match(line))


def is_image(line: str) -> bool:
    return bool(IMAGE_RE.match(line.strip()))


def is_block_component(line: str) -> bool:
    s = line.lstrip()
    return any(s.startswith(p) for p in BLOCK_COMPONENT_PREFIXES)


def normalize_indent(line: str) -> str:
    # Replace tabs with four spaces only at leading indentation
    if not line:
        return line
    # Split leading whitespace
    leading = len(line) - len(line.lstrip("\t "))
    prefix = line[:leading]
    suffix = line[leading:]
    prefix = prefix.replace("\t", " " * INDENT_SPACES)
    # For list items, ensure indent is a multiple of four spaces
    m = LIST_RE.match(prefix + suffix)
    if m:
        indent = m.group("indent")
        # Only spaces in indent by now
        spaces = len(indent)
        if spaces % INDENT_SPACES != 0:
            indent = " " * (spaces + (INDENT_SPACES - (spaces % INDENT_SPACES)))
        # Reconstruct with normalized indent and original rest
        marker = m.group("marker")
        rest = (prefix + suffix)[m.end():]
        return f"{indent}{marker} {rest}"
    return prefix + suffix


def merge_excess_blank_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    blank = False
    for ln in lines:
        if ln.strip() == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return out


def ensure_blank_lines_around_blocks(lines: List[str]) -> List[str]:
    out: List[str] = []
    in_code = False
    container_stack: List[str] = []
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if is_code_fence(line):
            # Treat code fences like advisory blocks w.r.t. spacing
            if not in_code:
                # Opening fence: ensure a blank line before, but none immediately after
                # Suppress the blank line if previous non-empty line is an immediate child open (Step/AccordionItem/Card)
                suppress_before = False
                if len(out) > 0:
                    # Find previous non-empty output line
                    k = len(out) - 1
                    while k >= 0 and out[k].strip() == "":
                        k -= 1
                    if k >= 0:
                        prev = out[k].lstrip()
                        if prev.startswith("<Step") or prev.startswith("<AccordionItem") or prev.startswith("<Card") or prev.startswith("<Tab"):
                            suppress_before = True
                if len(out) > 0 and out[-1].strip() != "" and not suppress_before:
                    out.append("")
                out.append(line)
                in_code = True
                i += 1
                # Remove any immediate blank lines after the opening fence
                while i < n and lines[i].strip() == "":
                    i += 1
                continue
            else:
                # Closing fence: no blank immediately before, add one after (unless next is a closing tag)
                if len(out) > 0 and out[-1].strip() == "":
                    out.pop()
                out.append(line)
                in_code = False
                # Look ahead to next non-empty original line
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                next_is_closing_tag = j < n and lines[j].lstrip().startswith("</")
                if not next_is_closing_tag:
                    out.append("")
                i += 1
                # Skip multiple blanks following in input
                while i < n and lines[i].strip() == "":
                    i += 1
                continue

        def is_open_container(l: str) -> bool:
            s = l.lstrip()
            return (
                s.startswith("<Steps")
                or s.startswith("<Accordion")
                or s.startswith("<AccordionGroup")
                or s.startswith("<Columns")
                or s.startswith("<CardGroup")
                or s.startswith("<CodeGroup")
                or s.startswith("<Frame")
                or s.startswith("<Warning")
                or s.startswith("<Info")
                or s.startswith("<Tip")
                or s.startswith("<Note")
            )

        def is_close_container(l: str) -> bool:
            s = l.lstrip()
            return (
                s.startswith("</Steps")
                or s.startswith("</Accordion")
                or s.startswith("</AccordionGroup")
                or s.startswith("</Columns")
                or s.startswith("</CardGroup")
                or s.startswith("</CodeGroup")
                or s.startswith("</Frame")
                or s.startswith("</Warning")
                or s.startswith("</Info")
                or s.startswith("</Tip")
                or s.startswith("</Note")
            )

        if not in_code:
            # Handle single-line advisory blocks like <Warning> ... </Warning>
            s_line_full = line.lstrip()
            m_single_adv = None
            for _name in ("Warning", "Info", "Tip", "Note"):
                if s_line_full.startswith(f"<{_name}") and f"</{_name}>" in s_line_full:
                    m_single_adv = _name
                    break
            if m_single_adv:
                # Check previous non-empty line for parent exception
                prev_non_empty = None
                for k in range(len(out) - 1, -1, -1):
                    if out[k].strip() != "":
                        prev_non_empty = out[k]
                        break
                prev_is_parent = False
                if prev_non_empty is not None:
                    p = prev_non_empty.lstrip()
                    if p.startswith("<Step") or p.startswith("<Accordion") or p.startswith("<Card"):
                        prev_is_parent = True
                if len(out) > 0 and out[-1].strip() != "" and not prev_is_parent:
                    out.append("")
                # If there is an existing blank line before and we're directly after an opening parent, remove it
                if prev_is_parent and len(out) > 0 and out[-1].strip() == "":
                    out.pop()
                out.append(line)
                # Look ahead to next non-empty line; suppress blank if it's a closing tag
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                next_is_closing_tag = False
                if j < n:
                    next_is_closing_tag = lines[j].lstrip().startswith("</")
                if not next_is_closing_tag:
                    out.append("")
                i += 1
                continue
            if False and is_open_container(line):
                # Determine if this is an advisory tag
                s_line = line.lstrip()
                is_advisory = s_line.startswith("<Warning") or s_line.startswith("<Info") or s_line.startswith("<Tip") or s_line.startswith("<Note")
                # Check previous non-empty line
                prev_non_empty = None
                for k in range(len(out) - 1, -1, -1):
                    if out[k].strip() != "":
                        prev_non_empty = out[k]
                        break
                prev_is_parent = False
                if prev_non_empty is not None:
                    p = prev_non_empty.lstrip()
                    if p.startswith("<Step") or p.startswith("<Accordion") or p.startswith("<Card"):
                        prev_is_parent = True
                # Ensure a blank line before unless it's an advisory directly after Step/Accordion/Card
                if len(out) > 0 and out[-1].strip() != "" and not (is_advisory and prev_is_parent):
                    out.append("")
                # If advisory follows an opening parent, remove any pre-existing blank line
                if is_advisory and prev_is_parent and len(out) > 0 and out[-1].strip() == "":
                    out.pop()
                out.append(line)
                # Track which container opened
                name = s_line[1:].split(None, 1)[0].rstrip(">/")
                container_stack.append(name)
                i += 1
                # Remove any immediate blank lines after the opening tag
                while i < n and lines[i].strip() == "":
                    i += 1
                continue
            if is_close_container(line):
                # Remove any immediate blank line before the closing tag
                if len(out) > 0 and out[-1].strip() == "":
                    out.pop()
                out.append(line)
                # Pop matching container if present and detect if it's advisory
                closed_name = None
                if container_stack:
                    closed_name = container_stack.pop()
                # Advisory blocks should normally be followed by a blank line
                s_line = line.lstrip()
                is_advisory_close = (
                    (closed_name in {"Warning", "Info", "Tip", "Note"})
                    or s_line.startswith("</Warning")
                    or s_line.startswith("</Info")
                    or s_line.startswith("</Tip")
                    or s_line.startswith("</Note")
                )
                # Look ahead to next non-empty original line
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                next_is_closing_tag = False
                if j < n:
                    next_is_closing_tag = lines[j].lstrip().startswith("</")

                if is_advisory_close:
                    # Add a blank line unless the next non-empty line is also a closing tag
                    if not next_is_closing_tag:
                        out.append("")
                    # Consume successive blank lines in input
                    i += 1
                    while i < n and lines[i].strip() == "":
                        i += 1
                    continue
                else:
                    # For non-advisory containers, ensure a blank line after
                    # unless the next non-empty line is also a closing tag
                    if not next_is_closing_tag:
                        nxt = lines[i + 1] if i + 1 < n else None
                        if nxt is not None and nxt.strip() != "":
                            out.append("")
                    i += 1
                    continue
            # Suppress image blank-line rules inside a <Frame>
            inside_frame = bool(container_stack and container_stack[-1] == "Frame")
            is_markdown_img = is_image(line)
            is_mdx_image = line.lstrip().startswith("<Image") or line.lstrip().startswith("<img")
            if is_heading(line) or ((is_markdown_img or is_mdx_image) and not inside_frame) or (is_block_component(line) and not inside_frame):
                # Ensure blank before and after for other block-ish lines (e.g., images)
                if len(out) > 0 and out[-1].strip() != "":
                    prev_non_empty = None
                    for k in range(len(out) - 1, -1, -1):
                        if out[k].strip() != "":
                            prev_non_empty = out[k].lstrip()
                            break
                    suppress_before = False
                    if prev_non_empty is not None:
                        if prev_non_empty.startswith("<Step") or prev_non_empty.startswith("<AccordionItem") or prev_non_empty.startswith("<Card"):
                            suppress_before = True
                    if not suppress_before:
                        out.append("")
                out.append(line)
                # Decide whether to add a blank after
                add_blank_after = True
                # For images, suppress blank after if the next non-empty line is a closing Step/Accordion/AccordionItem
                if (is_markdown_img or is_mdx_image) and not inside_frame:
                    j2 = i + 1
                    while j2 < n and lines[j2].strip() == "":
                        j2 += 1
                    if j2 < n:
                        next_ne = lines[j2].lstrip()
                        if next_ne.startswith("</Step") or next_ne.startswith("</Accordion") or next_ne.startswith("</AccordionItem"):
                            add_blank_after = False
                if add_blank_after:
                    nxt = lines[i + 1] if i + 1 < n else None
                    if nxt is not None and nxt.strip() != "":
                        out.append("")
                i += 1
                continue

        out.append(line)
        i += 1

    return merge_excess_blank_lines(out)


OPEN_TAG_RE = re.compile(r"^\s*<(?P<name>\w+)(\s|>)")
CLOSE_TAG_RE = re.compile(r"^\s*</(?P<name>\w+)\s*>")


def normalize_steps_indentation(lines: List[str]) -> List[str]:
    """Normalize indentation and spacing for group containers and their items.

    Supports:
    - <Steps> with child <Step>
    - <Accordion> with child <AccordionItem>
    - <Columns> with child <Card>
    - <Tabs> with child <Tab>

    Rules:
    - Blank line before container open and after container close.
    - Inside container: child open/close aligned at container indent + INDENT_SPACES.
    - Content inside child is indented one more level.
    - Remove blank lines immediately after child open and before child close.
    - Ensure exactly one blank line between sibling children; none before container close.
    """
    out: List[str] = []
    in_code = False
    # Stack of (name, indent, managed)
    stack: List[tuple[str, int, bool]] = []

    # Group to child mapping
    children_for = {
        "Steps": {"Step"},
        "Accordion": {"AccordionItem"},
        "AccordionGroup": {"Accordion"},
        "Columns": {"Card"},
        "CardGroup": {"Card"},
        "Tabs": {"Tab"},
    }

    SELF_CLOSING_RE = re.compile(r"^\s*<(?P<name>\w+)(?:[^>]*)/?>\s*$")

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Handle code fences
        if is_code_fence(line):
            in_code = not in_code
            out.append(line)
            i += 1
            continue
        if in_code:
            out.append(line)
            i += 1
            continue

        stripped = line.lstrip(" ")
        leading = len(line) - len(stripped)

        # Detect opening/closing tags
        m_open = OPEN_TAG_RE.match(line)
        m_close = CLOSE_TAG_RE.match(line)

        # Opening group containers
        if m_open and m_open.group("name") in children_for:
            # If nested inside a managed child (e.g., <Tab>/<Step>), align the container
            # as a content line inside that child.
            desired_leading = leading
            if stack:
                top_name, top_indent, _top_managed = stack[-1]
                # If the immediate parent is not a group container, treat it as a child-item.
                if top_name not in children_for:
                    desired_leading = top_indent + INDENT_SPACES
            # Ensure a blank line before
            if len(out) > 0 and out[-1].strip() != "":
                prev_non_empty = None
                for k in range(len(out) - 1, -1, -1):
                    if out[k].strip() != "":
                        prev_non_empty = out[k].lstrip()
                        break
                suppress_before = False
                if prev_non_empty is not None:
                    if prev_non_empty.startswith("<Step") or prev_non_empty.startswith("<AccordionItem") or prev_non_empty.startswith("<Card") or prev_non_empty.startswith("<Tab"):
                        suppress_before = True
                if not suppress_before:
                    out.append("")
            # Normalize indent of <Steps> tag itself (retain current leading)
            out.append(" " * desired_leading + stripped)
            stack.append((m_open.group("name"), desired_leading, True))
            # Skip immediate blank lines after opening
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            continue

        # Closing group containers
        if m_close and m_close.group("name") in children_for:
            # Align to stored indent if available
            cont_indent = leading
            for name, ind, _managed in reversed(stack):
                if name == m_close.group("name"):
                    cont_indent = ind
                    break
            # Remove preceding blank if any
            if len(out) > 0 and out[-1].strip() == "":
                out.pop()
            out.append(" " * cont_indent + stripped)
            # Pop matching container
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == m_close.group("name"):
                    stack.pop(j)
                    break
            # Ensure exactly one blank line after
            out.append("")
            i += 1
            # Skip multiple blanks following
            while i < n and lines[i].strip() == "":
                i += 1
            continue

        # Opening child items
        if m_open and stack and m_open.group("name") in children_for.get(stack[-1][0], set()):
            parent_indent = stack[-1][1]
            child_indent = parent_indent + INDENT_SPACES
            is_self_closing_child = stripped.endswith("/>")
            out.append(" " * child_indent + stripped)
            if not is_self_closing_child:
                stack.append((m_open.group("name"), child_indent, True))
            # Skip immediate blank lines after child open
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            # For self-closing children, add spacing similar to explicit close handling
            if is_self_closing_child:
                jn = i
                while jn < n and lines[jn].strip() == "":
                    jn += 1
                if jn < n:
                    next_lstrip = lines[jn].lstrip()
                    if not next_lstrip.startswith("</"):
                        out.append("")
            continue

        # Closing child items
        if m_close and m_close.group("name") in {"Step", "AccordionItem", "Card", "Tab"}:
            # Align to stored child indent
            child_indent = leading
            for name, ind, _managed in reversed(stack):
                if name == m_close.group("name"):
                    child_indent = ind
                    break
            # Remove preceding blank if any
            if len(out) > 0 and out[-1].strip() == "":
                out.pop()
            out.append(" " * child_indent + stripped)
            # Pop child
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == m_close.group("name"):
                    stack.pop(j)
                    break
            # Ensure spacing after child close:
            # - No blank before container close (next non-empty starts with </)
            # - Add one blank if the next non-empty is any opening tag or text (including imported snippets)
            jn = i + 1
            while jn < n and lines[jn].strip() == "":
                jn += 1
            if jn < n:
                next_lstrip = lines[jn].lstrip()
                if not next_lstrip.startswith("</"):
                    out.append("")
            i += 1
            # Skip any blank lines immediately after; our insertion above already handled spacing
            while i < n and lines[i].strip() == "":
                i += 1
            continue

        # Content lines: if inside a managed child (<Step>/<AccordionItem>/<Card>), indent by one more level
        inside_child = None
        managed_child = False
        for name, ind, managed in reversed(stack):
            if name in {"Step", "Accordion", "AccordionGroup", "AccordionItem", "Card", "Tab"}:
                inside_child = ind
                managed_child = managed
                break
        if inside_child is not None and stripped != "":
            if managed_child:
                if stripped.startswith("#"):
                    # Headings should always align to the left margin even inside managed containers
                    out.append(stripped)
                else:
                    content_indent = inside_child + INDENT_SPACES
                    out.append(" " * content_indent + stripped)
            else:
                out.append(line)
            i += 1
            continue

        # Self-closing component treated as child within group containers
        m_sc = SELF_CLOSING_RE.match(line)
        if m_sc and stack:
            parent_name, parent_indent, _ = stack[-1]
            # Only treat as child if parent is a known group container and this isn't a group close/open mismatch
            if parent_name in children_for and not stripped.startswith("</") and not stripped.startswith("<" + parent_name):
                child_indent = parent_indent + INDENT_SPACES
                out.append(" " * child_indent + stripped)
                # Ensure spacing after this pseudo-child: add one blank unless next is a closing container
                jn = i + 1
                while jn < n and lines[jn].strip() == "":
                    jn += 1
                if jn < n:
                    next_lstrip = lines[jn].lstrip()
                    if not next_lstrip.startswith("</"):
                        out.append("")
                i += 1
                # Skip subsequent blank lines in input to avoid duplicates
                while i < n and lines[i].strip() == "":
                    i += 1
                continue

        # Default: passthrough
        out.append(line)
        i += 1

    return merge_excess_blank_lines(out)


def wrap_line_to_width(line: str, width: int) -> List[str]:
    # Identify simple list prefix
    m = LIST_RE.match(line)
    if m:
        indent = m.group("indent")
        marker = m.group("marker")
        rest = line[m.end():]
        # Avoid wrapping risky content
        if ("`" in rest) or ("|" in rest) or ("<" in rest) or ("http" in rest):
            return [line]
        fill_width = max(20, width)  # safety
        eff_width = fill_width - len(indent) - len(marker) - 1
        lines = wrap_text_with_punct_preference(rest.strip(), eff_width)
        result = [f"{indent}{marker} {lines[0]}"]
        cont_indent = " " * (len(indent) + len(marker) + 1)
        for seg in lines[1:]:
            result.append(f"{cont_indent}{seg}")
        return result

    # Plain text line
    s = line.strip()
    if not s:
        return [line]
    if is_heading(line) or is_hr(line):
        return [line]
    if TABLE_RE.search(line):
        return [line]
    if line.lstrip().startswith(("<", ">")):
        return [line]

    # Preserve original left padding for paragraphs
    pad = len(line) - len(line.lstrip(" "))
    prefix = " " * pad
    wrapped_lines = wrap_text_with_punct_preference(s, width - pad)
    return [prefix + seg for seg in wrapped_lines]


def wrap_text_with_punct_preference(text: str, width: int) -> List[str]:
    """Wrap text preferring breaks after punctuation when possible.

    Does not break long words; if a single token exceeds width, it is placed on its own line.
    """
    if width <= 0:
        return [text]
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    cur_len = 0
    cur_words: List[str] = []
    last_punct_idx: int | None = None

    def is_punct_ending(w: str) -> bool:
        return bool(re.search(r"[\.,;:!\?\)\]\}]$", w))

    for w in words:
        if not cur_words:
            cur_words.append(w)
            cur_len = len(w)
            last_punct_idx = 1 if is_punct_ending(w) else None
            continue
        if cur_len + 1 + len(w) <= width:
            cur_words.append(w)
            cur_len += 1 + len(w)
            if is_punct_ending(w):
                last_punct_idx = len(cur_words)
            continue
        # Would overflow
        if last_punct_idx and last_punct_idx < len(cur_words) + 1:
            # Break at last punctuation within current words
            lines.append(" ".join(cur_words[: last_punct_idx]))
            # Remaining words include those after the break; current w not yet added
            remainder = cur_words[last_punct_idx:]
            cur_words = remainder or []
            cur_len = len(" ".join(cur_words)) if cur_words else 0
            last_punct_idx = None
            # Reprocess current word in next iteration by simulating step back
            if not cur_words:
                # start new line with w
                cur_words = [w]
                cur_len = len(w)
                last_punct_idx = 1 if is_punct_ending(w) else None
            else:
                # Try to add w now if it fits, otherwise force line
                if cur_len + (1 if cur_words else 0) + len(w) <= width:
                    cur_words.append(w)
                    cur_len += 1 + len(w)
                    if is_punct_ending(w):
                        last_punct_idx = len(cur_words)
                else:
                    # Flush current as is
                    lines.append(" ".join(cur_words))
                    cur_words = [w]
                    cur_len = len(w)
                    last_punct_idx = 1 if is_punct_ending(w) else None
            continue
        # No punctuation to break at: break at last whitespace (i.e., before this word)
        if cur_words:
            lines.append(" ".join(cur_words))
        cur_words = [w]
        cur_len = len(w)
        last_punct_idx = 1 if is_punct_ending(w) else None

    if cur_words:
        lines.append(" ".join(cur_words))
    return lines


def wrap_long_lines(lines: List[str], width: int) -> List[str]:
    """Reflow and wrap paragraphs to the target width.

    - Operates outside of fenced code blocks.
    - Preserves headings, tables, MDX/HTML tag lines as-is and treats them as paragraph boundaries.
    - Handles list items with list-aware wrapping, keeping continuation indentation.
    - For plain paragraphs, collapses internal newlines and rewraps to the target width.
    """
    out: List[str] = []
    in_code = False
    in_frontmatter = False
    para: List[str] = []

    def flush_para():
        nonlocal para
        if not para:
            return
        # Determine minimal left padding among non-empty lines
        pads = [len(p) - len(p.lstrip(" ")) for p in para if p.strip()]
        pad = min(pads) if pads else 0
        prefix = " " * pad
        # Build paragraph text by joining with spaces
        text = " ".join(p.strip() for p in para).strip()
        if not text:
            out.append("")
        else:
            wrapped_lines = wrap_text_with_punct_preference(text, max(20, width - pad))
            out.extend(prefix + seg for seg in wrapped_lines)
        para = []

    for ln in lines:
        # YAML frontmatter guard (only at file start)
        if not out and not para and ln.strip() == "---":
            in_frontmatter = True
            out.append(ln)
            continue
        if in_frontmatter:
            out.append(ln)
            if ln.strip() == "---":
                in_frontmatter = False
            continue

        if is_code_fence(ln):
            flush_para()
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue

        stripped = ln.strip()
        if stripped == "":
            flush_para()
            out.append("")
            continue

        # Boundaries and special lines
        stripped_l = ln.lstrip()
        if is_heading(ln) or is_hr(ln) or TABLE_RE.search(ln) or stripped_l.startswith(("<", ">")) or stripped_l.startswith("import ") or stripped_l.startswith("export "):
            flush_para()
            out.append(ln)
            continue

        # List items are handled individually to preserve markers and continuation indentation
        if LIST_RE.match(ln):
            flush_para()
            out.extend(wrap_line_to_width(ln, width))
            continue

        # Accumulate paragraph text
        para.append(ln)

    flush_para()
    return out


def format_content(text: str, width: int) -> str:
    # Repair accidentally inlined YAML frontmatter keys (if present)
    def fix_frontmatter(blob: str) -> str:
        if not blob.startswith("---\n"):
            return blob
        end = blob.find("\n---", 4)
        if end == -1:
            return blob
        header = blob[4:end]
        # If any line contains more than one key pattern, split them
        # Insert a newline before key-like tokens that follow spaces on the same line
        fixed_header = re.sub(r"(?<!\n)\s+([A-Za-z_][\w-]*:\s*)", r"\n\1", header)
        # Collapse wrapped values for common fields onto one line
        lines = [ln for ln in fixed_header.splitlines() if ln.strip() != ""]
        out_lines: List[str] = []
        current_key = None
        current_val_parts: List[str] = []
        def flush_kv():
            nonlocal current_key, current_val_parts
            if current_key is None:
                return
            value = " ".join(s.strip() for s in current_val_parts).strip()
            value_norm = value.replace('\\"', '"')
            # If the value became double-quoted at both ends (e.g., ""Text""), collapse to single quotes
            if value_norm.startswith('""') and value_norm.endswith('""') and len(value_norm) >= 4:
                value_norm = value_norm[1:-1]
            # Check if value is a boolean (true/false) - don't quote these
            if value_norm.lower() in ('true', 'false'):
                value_quoted = value_norm.lower()
            # Keep existing quotes if already quoted; otherwise quote with double quotes
            elif (len(value_norm) >= 2 and ((value_norm.startswith('"') and value_norm.endswith('"')) or (value_norm.startswith("'") and value_norm.endswith("'")))):
                value_quoted = value_norm
            else:
                value_quoted = '"' + value_norm.replace('"', '\\"') + '"'
            out_lines.append(f"{current_key}: {value_quoted}")
            current_key = None
            current_val_parts = []
        for ln in lines:
            m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
            if m:
                # New key
                flush_kv()
                current_key = m.group(1)
                rest = m.group(2)
                current_val_parts = [rest] if rest is not None else []
            else:
                # Continuation line for previous key
                if current_key is not None:
                    current_val_parts.append(ln)
                else:
                    out_lines.append(ln)
        flush_kv()
        rebuilt = "\n".join(out_lines)
        return "---\n" + rebuilt.strip("\n") + blob[end:]

    text = fix_frontmatter(text)

    # Split preserving line endings as \n
    raw_lines = text.splitlines()

    # 1) Normalize indentation (outside code blocks)
    lines: List[str] = []
    in_code = False
    for ln in raw_lines:
        if is_code_fence(ln):
            in_code = not in_code
            lines.append(ln)  # Don't normalize fence lines themselves
            continue
        if in_code:
            lines.append(ln)  # Don't normalize lines inside code blocks
        else:
            lines.append(normalize_indent(ln))  # Only normalize outside code blocks

    # 2) Dedent common leading margin across the file (outside code and frontmatter)
    def dedent_common_margin(ls: List[str]) -> List[str]:
        out_ls: List[str] = []
        in_code_f = False
        in_front = False
        # Compute minimal leading spaces among relevant lines
        mins: List[int] = []
        for i, l in enumerate(ls):
            if i == 0 and l.strip() == "---":
                in_front = True
            elif in_front and l.strip() == "---":
                in_front = False
            if is_code_fence(l):
                in_code_f = not in_code_f
                continue
            if in_code_f or in_front:
                continue
            if l.strip() == "":
                continue
            # count spaces only
            lead = len(l) - len(l.lstrip(" "))
            mins.append(lead)
        if not mins:
            return ls
        common = min(mins)
        if common <= 0:
            return ls
        for l in ls:
            # Only trim spaces, not tabs (tabs already normalized earlier)
            if l.startswith(" " * common):
                out_ls.append(l[common:])
            else:
                out_ls.append(l)
        return out_ls

    lines = dedent_common_margin(lines)

    # 3) Normalize <Steps>/<Step> indentation and spacing
    lines = normalize_steps_indentation(lines)

    # 4) Expand single-line advisory tags (<Warning>/<Info>/<Tip>/<Note>) to multi-line with indented content
    def expand_single_line_advisories(ls: List[str]) -> List[str]:
        out_ls: List[str] = []
        in_code_f = False
        pat = re.compile(r"^(?P<indent>\s*)<(?P<name>Warning|Info|Tip|Note)(?P<attrs>[^>]*)>(?P<inner>.*?)</(?P=name)>\s*$")
        for ln in ls:
            if is_code_fence(ln):
                in_code_f = not in_code_f
                out_ls.append(ln)
                continue
            if in_code_f:
                out_ls.append(ln)
                continue
            m = pat.match(ln)
            if m:
                indent = m.group("indent")
                name = m.group("name")
                attrs = m.group("attrs") or ""
                inner = m.group("inner").strip()
                out_ls.append(f"{indent}<{name}{attrs}>")
                out_ls.append(f"{indent}{' ' * INDENT_SPACES}{inner}")
                out_ls.append(f"{indent}</{name}>")
            else:
                out_ls.append(ln)
        return out_ls

    lines = expand_single_line_advisories(lines)

    # 5) Normalize indentation of content inside specific containers
    def normalize_inner_indentation(ls: List[str]) -> List[str]:
        target_names = {"Warning", "Info", "Tip", "Note", "Frame", "CodeGroup"}
        out_ls: List[str] = []
        in_code_f = False
        stack: List[tuple[str, int]] = []  # (name, base_indent)
        for ln in ls:
            if is_code_fence(ln):
                in_code_f = not in_code_f
                s_cf = ln.lstrip(" ")
                # Indent code fence lines when inside CodeGroup
                if stack and stack[-1][0] == "CodeGroup":
                    base = stack[-1][1]
                    desired = base + INDENT_SPACES
                    out_ls.append(" " * desired + s_cf)
                else:
                    out_ls.append(ln)
                continue
            if in_code_f:
                # While inside a fenced code block: never modify content, preserve exactly as-is
                out_ls.append(ln)
                continue

            s = ln.lstrip(" ")
            leading = len(ln) - len(s)

            m_open = OPEN_TAG_RE.match(ln)
            m_close = CLOSE_TAG_RE.match(ln)

            if m_open and m_open.group("name") in target_names:
                out_ls.append(" " * leading + s)
                stack.append((m_open.group("name"), leading))
                continue

            if m_close and stack and m_close.group("name") == stack[-1][0]:
                name, base = stack.pop()
                out_ls.append(" " * base + s)
                continue

            if stack:
                # Inside one of the target containers: enforce indent for content lines
                name, base = stack[-1]
                if s.strip() == "":
                    out_ls.append("")
                else:
                    desired = base + INDENT_SPACES
                    out_ls.append(" " * desired + s)
            else:
                out_ls.append(ln)

        return out_ls

    lines = normalize_inner_indentation(lines)

    # 6) Enforce blank lines around container-level blocks
    lines = ensure_blank_lines_around_blocks(lines)

    # 6.5) Normalize MDX import/export lines and fix merged imports
    def normalize_mdx_imports(ls: List[str]) -> List[str]:
        out_ls: List[str] = []
        in_code_f = False
        imp_pat = re.compile(r"\bimport\s+[^\n\r;]*?\s+from\s+['\"][^'\"]+['\"]")
        for ln in ls:
            if is_code_fence(ln):
                in_code_f = not in_code_f
                out_ls.append(ln)
                continue
            if in_code_f:
                out_ls.append(ln)
                continue
            s = ln.lstrip()
            lead = ln[: len(ln) - len(s)]
            if s.startswith("import "):
                parts = imp_pat.findall(s)
                if parts and len(parts) > 1:
                    for p in parts:
                        out_ls.append(lead + p)
                    continue
            # Repair lines missing 'import' due to previous wrapping, e.g., 'Name from "..."'
            if re.match(r"^[A-Za-z_][\w]*\s+from\s+['\"]", s):
                out_ls.append(lead + "import " + s)
                continue
            out_ls.append(ln)
        return out_ls

    lines = normalize_mdx_imports(lines)

    # 6.7) Remove any blank line immediately after group container opens
    def remove_blank_after_group_opens(ls: List[str]) -> List[str]:
        out_ls: List[str] = []
        in_code_f = False
        opens = ("<Steps", "<AccordionGroup", "<Accordion", "<Columns", "<CardGroup", "<CodeGroup", "<Tabs", "<Tab")
        i2 = 0
        n2 = len(ls)
        while i2 < n2:
            cur = ls[i2]
            if is_code_fence(cur):
                in_code_f = not in_code_f
                out_ls.append(cur)
                i2 += 1
                continue
            if not in_code_f and cur.lstrip().startswith(opens):
                out_ls.append(cur)
                # Skip exactly one following blank line if present
                j2 = i2 + 1
                if j2 < n2 and ls[j2].strip() == "":
                    i2 = j2 + 1
                    continue
                i2 += 1
                continue
            out_ls.append(cur)
            i2 += 1
        return out_ls

    lines = remove_blank_after_group_opens(lines)

    # 6.8) Normalize img tag format: className first, then src, then alt, then other attributes
    def normalize_img_tags(ls: List[str]) -> List[str]:
        out_ls: List[str] = []
        in_code_f = False
        # Pattern to match complete img tag (handles multi-line by joining)
        # Match: <img ... /> or <img ... >
        img_start_pattern = re.compile(r"<img\s+", re.IGNORECASE)
        # Pattern to extract all attribute values: attr="value" or attr='value' or attr={value}
        # For JSX-style attributes with nested braces, we need a more sophisticated approach
        def extract_attributes(content: str) -> dict[str, str]:
            """Extract all attributes from an img tag, handling both quoted and JSX-style attributes."""
            attrs: dict[str, str] = {}
            # Pattern for quoted attributes: attr="value" or attr='value'
            quoted_pattern = re.compile(r'(\w+)\s*=\s*(["\'])([^"\']*)\2', re.IGNORECASE)
            for match in quoted_pattern.finditer(content):
                attr_name = match.group(1).lower()
                quote_char = match.group(2)
                attr_value = match.group(3)
                attrs[attr_name] = f'{quote_char}{attr_value}{quote_char}'
            
            # Pattern for JSX-style attributes: attr={...}
            # We need to handle nested braces, so we'll find the opening { and match the closing }
            jsx_pattern = re.compile(r'(\w+)\s*=\s*(\{)', re.IGNORECASE)
            pos = 0
            while True:
                match = jsx_pattern.search(content, pos)
                if not match:
                    break
                attr_name = match.group(1).lower()
                brace_start = match.start(2)
                # Find matching closing brace
                brace_count = 0
                brace_end = brace_start
                for i in range(brace_start, len(content)):
                    if content[i] == '{':
                        brace_count += 1
                    elif content[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            brace_end = i
                            break
                if brace_count == 0:
                    attr_value = content[brace_start:brace_end + 1]
                    attrs[attr_name] = attr_value
                pos = brace_end + 1
            
            return attrs
        
        i = 0
        n = len(ls)
        while i < n:
            ln = ls[i]
            if is_code_fence(ln):
                in_code_f = not in_code_f
                out_ls.append(ln)
                i += 1
                continue
            if in_code_f:
                out_ls.append(ln)
                i += 1
                continue
            
            stripped = ln.lstrip()
            leading = len(ln) - len(stripped)
            
            # Check if line starts with <img
            if img_start_pattern.match(stripped):
                # Collect the full img tag (may span multiple lines)
                # Only collect lines that are part of the img tag, not blank lines or other tags
                img_parts = [stripped]
                j = i + 1
                tag_closed = False
                
                # Check if tag is already closed on this line (ends with /> or >)
                stripped_rstrip = stripped.rstrip()
                if stripped_rstrip.endswith("/>") or stripped_rstrip.endswith(">"):
                    tag_closed = True
                
                # Collect continuation lines until tag is closed
                # Stop immediately if we hit a blank line, code fence, or other tag
                while j < n and not tag_closed:
                    if is_code_fence(ls[j]):
                        break
                    # Stop if we hit a blank line (img tag shouldn't span blank lines)
                    if ls[j].strip() == "":
                        break
                    next_line = ls[j].lstrip()
                    # Stop if next line starts a new tag or component (but allow if it's another img tag continuation)
                    if next_line.startswith("<"):
                        # If it's not an img tag, stop collecting - this line is NOT part of the img tag
                        if not img_start_pattern.match(next_line):
                            break
                    # This line is part of the img tag, add it
                    img_parts.append(next_line)
                    next_rstrip = next_line.rstrip()
                    if next_rstrip.endswith("/>") or next_rstrip.endswith(">"):
                        tag_closed = True
                        break
                    j += 1
                
                # Join all parts into a single string for processing
                img_content = " ".join(img_parts)
                
                # Extract all attributes using the helper function
                attrs = extract_attributes(img_content)
                
                # Extract values for required attributes
                className_val = None
                class_val = None  # fallback for "class" attribute
                src_val = None
                alt_val = None
                
                for attr_name, attr_value in attrs.items():
                    if attr_name == "classname":
                        # Extract value, handling both quoted and JSX-style
                        if attr_value.startswith("{") and attr_value.endswith("}"):
                            className_val = attr_value[1:-1].strip().strip('"').strip("'")
                        else:
                            className_val = attr_value.strip('"').strip("'")
                    elif attr_name == "class":
                        if attr_value.startswith("{") and attr_value.endswith("}"):
                            class_val = attr_value[1:-1].strip().strip('"').strip("'")
                        else:
                            class_val = attr_value.strip('"').strip("'")
                    elif attr_name == "src":
                        if attr_value.startswith("{") and attr_value.endswith("}"):
                            src_val = attr_value[1:-1].strip().strip('"').strip("'")
                        else:
                            src_val = attr_value.strip('"').strip("'")
                    elif attr_name == "alt":
                        if attr_value.startswith("{") and attr_value.endswith("}"):
                            alt_val = attr_value[1:-1].strip().strip('"').strip("'")
                        else:
                            alt_val = attr_value.strip('"').strip("'")
                
                # Use className if available, otherwise fall back to class
                if not className_val and class_val:
                    className_val = class_val
                    # Update attrs dict to use className instead of class
                    if "classname" not in attrs:
                        attrs["classname"] = attrs.pop("class", f'"{class_val}"')
                
                # Build normalized img tag if we have all required attributes
                if className_val and src_val and alt_val:
                    # Determine closing style
                    is_self_closing = "/>" in img_content
                    closing = "/>" if is_self_closing else ">"
                    
                    # Build attribute list: className first, then src, then alt, then others
                    attr_parts = []
                    # Add className first
                    if "classname" in attrs:
                        attr_parts.append(f'className={attrs["classname"]}')
                    # Add src second
                    if "src" in attrs:
                        attr_parts.append(f'src={attrs["src"]}')
                    # Add alt third
                    if "alt" in attrs:
                        attr_parts.append(f'alt={attrs["alt"]}')
                    # Add all other attributes (preserve original order)
                    for attr_name, attr_value in attrs.items():
                        if attr_name not in {"classname", "class", "src", "alt"}:
                            attr_parts.append(f'{attr_name}={attr_value}')
                    
                    normalized = f'<img {" ".join(attr_parts)} {closing}'.replace(" />", "/>").replace(" >", ">")
                    out_ls.append(" " * leading + normalized)
                    # IMPORTANT: j points to the first line AFTER the img tag
                    # This could be a blank line, closing tag like </Step>, or another element
                    # We set i = j so the next iteration processes that line normally
                    i = j
                else:
                    # If any required attribute is missing, keep original lines
                    # Output all lines from i to j-1 (the img tag lines)
                    for k in range(i, j):
                        out_ls.append(ls[k])
                    # Move to line j (first line after img tag)
                    i = j
            else:
                # Not an img tag line, preserve as-is
                out_ls.append(ln)
                i += 1
        
        return out_ls

    lines = normalize_img_tags(lines)

    # 7) Wrap long lines (outside code blocks)
    lines = wrap_long_lines(lines, width)

    # 8) Remove trailing whitespace on every line
    def strip_trailing_ws(ls: List[str]) -> List[str]:
        return [l.rstrip() for l in ls]

    lines = strip_trailing_ws(lines)

    # Always ensure exactly one trailing newline at EOF
    return ("\n".join(lines)).rstrip("\n") + "\n"


def process_file(path: str, write: bool, width: int) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except UnicodeDecodeError:
        # Skip non-UTF8 files
        return False

    formatted = format_content(original, width)
    if formatted != original:
        if write:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(formatted)
        return True
    return False


def find_numbered_list_spacing_warnings(path: str, text: str) -> List[tuple[int, str]]:
    warnings: List[tuple[int, str]] = []
    in_code = False
    for idx, ln in enumerate(text.splitlines(), start=1):
        if is_code_fence(ln):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Ignore MDX/HTML lines and tables
        if ln.lstrip().startswith(("<", ">")):
            continue
        if TABLE_RE.search(ln):
            continue
        m = BAD_NUM_LIST_RE.match(ln)
        if m:
            # m.group(1) is the first non-space char after the marker
            warnings.append((idx, ln.rstrip()))
    return warnings


def find_numbered_list_occurrences(path: str, text: str) -> List[tuple[int, str]]:
    found: List[tuple[int, str]] = []
    in_code = False
    for idx, ln in enumerate(text.splitlines(), start=1):
        if is_code_fence(ln):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Ignore MDX/HTML lines and tables
        if ln.lstrip().startswith(("<", ">")):
            continue
        if TABLE_RE.search(ln):
            continue
        if ANY_NUM_LIST_RE.match(ln):
            found.append((idx, ln.rstrip()))
    return found


def run_mintlify_broken_links(root: str) -> int:
    """Attempt to run `<cli> broken-links` and print its output.

    `mint` is the current Mintlify CLI; `mintlify` is its former name. Both
    expose `broken-links`, so prefer `mint` and fall back to `mintlify`.

    Returns the subprocess return code if executed, otherwise 0.
    """
    for cli_name in ("mint", "mintlify"):
        cli = shutil.which(cli_name)
        if cli:
            break
    else:
        print("Mintlify CLI not found. Skipping broken-links check.")
        print("Install with: npm i -g mint")
        return 0
    try:
        print(f"Running: {cli_name} broken-links")
        proc = subprocess.run(
            [cli, "broken-links"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        # Forward stdout/stderr to user
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        return proc.returncode
    except Exception as e:
        print(f"Failed to run {cli_name} broken-links: {e}")
        return 1


LINK_MD_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
IMG_MDX_RE = re.compile(r"<(?:img|Image)[^>]*\s+src=\"([^\"]+)\"[\s\S]*?/?>")


def fallback_broken_asset_check(root: str, path: str, text: str) -> List[tuple[int, str, str]]:
    """Simple local-asset existence check for links/images when mintlify is unavailable.

    Returns list of (line_number, kind, target) for missing local targets.
    Only checks paths that look local (start with '/' or relative paths without schema).
    """
    results: List[tuple[int, str, str]] = []
    in_code = False
    for idx, ln in enumerate(text.splitlines(), start=1):
        if is_code_fence(ln):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Collect candidates from Markdown links/images
        targets: List[tuple[str, str]] = []  # (kind, target)
        for m in IMG_MD_RE.finditer(ln):
            targets.append(("image", m.group(1)))
        for m in LINK_MD_RE.finditer(ln):
            targets.append(("link", m.group(1)))
        for m in IMG_MDX_RE.finditer(ln):
            targets.append(("image", m.group(1)))

        for kind, target in targets:
            t = target.strip()
            # Skip anchors and mailto and http(s)
            if t.startswith("#") or "://" in t or t.startswith("mailto:"):
                continue
            # Normalize path
            if t.startswith("/"):
                candidate = os.path.join(root, t.lstrip("/"))
            else:
                candidate = os.path.join(os.path.dirname(os.path.join(root, path)), t)
            if not os.path.exists(candidate):
                results.append((idx, kind, t))
    return results


SKILL_LINK_DIRS = (".claude/skills", ".cursor/skills", ".codex/skills")
SKILLS_ROOT = ".agents/skills"


def find_skills_layout_errors(root: str) -> List[str]:
    """Every agent skills dir must be a symlink to .agents/skills, and every skill needs a SKILL.md."""
    errors: List[str] = []
    skills_root = os.path.join(root, SKILLS_ROOT)
    if not os.path.isdir(skills_root):
        return [f"{SKILLS_ROOT} is missing"]
    for rel in SKILL_LINK_DIRS:
        link = os.path.join(root, rel)
        if not os.path.islink(link):
            errors.append(f"{rel} must be a symlink to {SKILLS_ROOT}")
            continue
        if os.path.realpath(link) != os.path.realpath(skills_root):
            errors.append(f"{rel} points to {os.readlink(link)}, expected {SKILLS_ROOT}")
    for name in sorted(os.listdir(skills_root)):
        skill_dir = os.path.join(skills_root, name)
        if os.path.isdir(skill_dir) and not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
            errors.append(f"{SKILLS_ROOT}/{name} has no SKILL.md")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Format Markdown/MDX docs")
    parser.add_argument("--check", action="store_true", help="Only report files that would change")
    parser.add_argument("--write", action="store_true", help="Write changes to files")
    parser.add_argument("--width", type=int, default=120, help="Wrap width for text lines")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="Optional list of files/directories to format (defaults to entire repo).",
    )
    # Link checks always run; flag retained for compatibility but ignored
    parser.add_argument("--check-links", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.check and not args.write:
        print("Specify --check or --write", file=sys.stderr)
        return 2

    root = os.getcwd()
    if args.paths:
        files: List[str] = []
        for p in args.paths:
            abspath = os.path.abspath(p)
            if os.path.isdir(abspath):
                files.extend(iter_doc_files(abspath))
            else:
                files.append(abspath)
    else:
        files = iter_doc_files(root)
    changed: List[str] = []
    numbered_list_warnings: List[tuple[str, int, str]] = []
    numbered_list_found: List[tuple[str, int, str]] = []
    frontmatter_icon_warnings: List[str] = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                original = f.read()
        except UnicodeDecodeError:
            original = ""
        if original:
            # Frontmatter icon check (skip for admins/connectors/* pages)
            if original.startswith("---\n"):
                end = original.find("\n---", 4)
                if end != -1:
                    header = original[4:end]
                    has_icon = any(re.match(r"^icon:\s*", ln.strip()) for ln in header.splitlines())
                    rel = os.path.relpath(p, root).replace("\\", "/")
                    is_exempt = (
                        rel.startswith("admins/connectors/")
                        or rel.startswith("snippets/")
                        or rel.startswith("developers/api_reference/")
                        or rel.startswith("deployment/cloud/aws")
                    )
                    if not has_icon and not is_exempt:
                        frontmatter_icon_warnings.append(p)
            for ln_no, ln_text in find_numbered_list_spacing_warnings(p, original):
                numbered_list_warnings.append((p, ln_no, ln_text))
            for ln_no, ln_text in find_numbered_list_occurrences(p, original):
                numbered_list_found.append((p, ln_no, ln_text))
        if process_file(p, write=args.write, width=args.width):
            changed.append(p)

    # Emit numbered list warnings (informational, non-fatal)
    if numbered_list_found:
        print("Numbered lists detected (consider using <Steps>/<Step> where appropriate):")
        for p, ln_no, ln_text in numbered_list_found:
            print(f"  {p}:{ln_no}: '{ln_text}'")
    # Emit numbered list spacing warnings (missing space after numeric marker)
    if numbered_list_warnings:
        print("Numbered list spacing warnings (missing space after numeric marker):")
        for p, ln_no, ln_text in numbered_list_warnings:
            print(f"  {p}:{ln_no}: '{ln_text}'")

    if frontmatter_icon_warnings:
        print("Frontmatter warnings: missing 'icon' field (all pages should have icons):")
        for p in frontmatter_icon_warnings:
            print(f"  {p}")

    skills_layout_errors = find_skills_layout_errors(root) if not args.paths else []
    if skills_layout_errors:
        print("Agent skills layout errors:")
        for e in skills_layout_errors:
            print(f"  {e}")

    # Always run link check via the Mintlify CLI if available (no fallback)
    rc = run_mintlify_broken_links(root)
    if rc != 0:
        print(f"broken-links exited with code {rc}")

    if args.check:
        if skills_layout_errors:
            return 1
        if changed:
            print(f"{len(changed)} file(s) would be reformatted:")
            for p in changed:
                print(p)
            return 1
        else:
            print("All files are correctly formatted.")
            return 0
    else:
        print(f"Reformatted {len(changed)} file(s).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
