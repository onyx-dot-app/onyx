#!/usr/bin/env python3
"""Generate the standalone docker compose files from docker-compose.template.yml.

docker-compose.yml, docker-compose.prod.yml and docker-compose.prod-no-letsencrypt.yml
are generated files. Edit docker-compose.template.yml instead, then regenerate with:

    python3 deployment/docker_compose/generate_compose.py --write

Without --write the script runs in check mode: it prints a diff and exits non-zero
if any generated file is out of date. The docker-compose-sync pre-commit hook runs
--write automatically for commits touching the template or the generated files.

Template directives are line comments starting with the sentinel `#!`. They are
always stripped from the output. <variants> is a comma-separated subset of:
default, prod, no-letsencrypt (mapping to the three generated files above).

    #!for <variants>            include the enclosed lines only for <variants>;
    ...                         must be closed with #!endfor, no nesting
    #!endfor

    #!only <variants>           shorthand: applies to exactly the next line

    #!value <variants>: <text>  per-variant text for the line that follows: the
                                directive's own indentation plus <text> replaces
                                the next line for the listed variants; unlisted
                                variants keep the line as written. Stack several
                                #!value directives for three-way splits.

    #!# <text>                  template-only comment, never emitted

The script is standard-library-only on purpose, so any python3 can run it with no
environment setup (it is invoked as a plain `python3` pre-commit hook).
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

VARIANTS: dict[str, str] = {
    "default": "docker-compose.yml",
    "prod": "docker-compose.prod.yml",
    "no-letsencrypt": "docker-compose.prod-no-letsencrypt.yml",
}

TEMPLATE_NAME = "docker-compose.template.yml"

BANNER_LINES: list[str] = [
    "# =============================================================================",
    "# THIS FILE IS GENERATED - DO NOT EDIT DIRECTLY",
    "# Source of truth: deployment/docker_compose/docker-compose.template.yml",
    "# Regenerate:      python3 deployment/docker_compose/generate_compose.py --write",
    "# =============================================================================",
]


class TemplateError(Exception):
    """A structural error in the template (bad directive, unclosed block, ...)."""

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"{TEMPLATE_NAME}:{line_no}: {message}")


def _parse_variants(spec: str, line_no: int) -> frozenset[str]:
    names = spec.split(",")
    seen: list[str] = []
    for name in names:
        if name not in VARIANTS:
            known = ", ".join(VARIANTS)
            raise TemplateError(
                line_no, f"unknown variant {name!r} (known variants: {known})"
            )
        if name in seen:
            raise TemplateError(line_no, f"variant {name!r} listed twice")
        seen.append(name)
    return frozenset(seen)


Directive = tuple[str, frozenset[str], str]


def _parse_directive(body: str, line_no: int) -> Directive:
    """Parse the text after the `#!` sentinel into (kind, variants, value_text)."""
    if body.startswith("#"):
        return ("comment", frozenset(), "")
    if body.strip() == "endfor":
        return ("endfor", frozenset(), "")
    if body.startswith("for "):
        return ("for", _parse_variants(body[len("for ") :].strip(), line_no), "")
    if body.startswith("only "):
        return ("only", _parse_variants(body[len("only ") :].strip(), line_no), "")
    if body.startswith("value "):
        rest = body[len("value ") :]
        colon = rest.find(":")
        if colon < 0:
            raise TemplateError(
                line_no,
                "malformed #!value directive (expected '#!value <variants>: <text>')",
            )
        variants = _parse_variants(rest[:colon].strip(), line_no)
        text = rest[colon + 1 :]
        return ("value", variants, text.removeprefix(" "))
    word = body.split()[0] if body.split() else ""
    raise TemplateError(line_no, f"unknown template directive: #!{word}")


def render(template_lines: Sequence[str], variant: str) -> list[str]:
    """Render the template for one variant. Raises TemplateError on bad structure."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")

    out: list[str] = []
    for_block: tuple[frozenset[str], int] | None = None
    pending_only: tuple[frozenset[str], int] | None = None
    # Stacked #!value directives waiting for their base line, plus the union of
    # variants they claim (to reject double claims / fully-claimed base lines).
    pending_values: list[tuple[frozenset[str], str]] = []
    claimed: set[str] = set()

    def in_scope() -> bool:
        return for_block is None or variant in for_block[0]

    for line_no, raw in enumerate(template_lines, start=1):
        stripped = raw.lstrip()
        if stripped.startswith("#!"):
            indent = raw[: len(raw) - len(stripped)]
            kind, variants, text = _parse_directive(stripped[2:], line_no)
            if pending_only is not None:
                raise TemplateError(
                    line_no, "#!only must be immediately followed by a content line"
                )
            if pending_values and kind != "value":
                raise TemplateError(
                    line_no,
                    "#!value must be immediately followed by a content line "
                    "or another #!value",
                )
            if kind == "comment":
                continue
            if kind == "for":
                if for_block is not None:
                    raise TemplateError(
                        line_no,
                        f"nested #!for (previous block opened at line {for_block[1]})",
                    )
                for_block = (variants, line_no)
            elif kind == "endfor":
                if for_block is None:
                    raise TemplateError(line_no, "#!endfor without matching #!for")
                for_block = None
            elif kind == "only":
                pending_only = (variants, line_no)
            else:  # value
                overlap = variants & claimed
                if overlap:
                    raise TemplateError(
                        line_no,
                        f"variant(s) {', '.join(sorted(overlap))} already claimed "
                        "by a stacked #!value",
                    )
                claimed.update(variants)
                if claimed >= VARIANTS.keys():
                    raise TemplateError(
                        line_no,
                        "stacked #!value directives cover every variant; the base "
                        "line below would never be emitted",
                    )
                pending_values.append((variants, indent + text if text else ""))
            continue

        # Content line.
        if pending_only is not None:
            only_variants, _ = pending_only
            pending_only = None
            if variant in only_variants and in_scope():
                out.append(raw)
        elif pending_values:
            replacement = next(
                (
                    text
                    for value_variants, text in pending_values
                    if variant in value_variants
                ),
                None,
            )
            pending_values = []
            claimed = set()
            if in_scope():
                out.append(raw if replacement is None else replacement)
        elif in_scope():
            out.append(raw)

    if for_block is not None:
        raise TemplateError(for_block[1], "unclosed #!for block (missing #!endfor)")
    if pending_only is not None:
        raise TemplateError(pending_only[1], "#!only at end of file")
    if pending_values:
        raise TemplateError(len(template_lines), "#!value at end of file")
    return out


def _check_yaml(content: str, filename: str) -> str | None:
    """Best-effort YAML parse check; skipped when PyYAML isn't installed."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        yaml.safe_load(content)
    except Exception as exc:  # noqa: BLE001 - report any parse failure
        return f"{filename}: generated YAML does not parse: {exc}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the docker compose files from the shared template."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write", action="store_true", help="rewrite the generated files"
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if the generated files are out of date (default)",
    )
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    template_path = here / TEMPLATE_NAME
    if not template_path.is_file():
        print(f"error: {template_path} not found", file=sys.stderr)
        return 1
    template_lines = template_path.read_text().splitlines()

    rendered: dict[str, str] = {}
    try:
        for variant, filename in VARIANTS.items():
            body = render(template_lines, variant)
            leaked = [line for line in body if line.lstrip().startswith("#!")]
            if leaked:
                raise TemplateError(
                    0,
                    f"internal error: directive leaked into {filename}: {leaked[0]!r}",
                )
            rendered[filename] = "\n".join([*BANNER_LINES, *body]) + "\n"
    except TemplateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for filename, content in rendered.items():
        yaml_error = _check_yaml(content, filename)
        if yaml_error is not None:
            print(f"error: {yaml_error}", file=sys.stderr)
            return 1

    stale: list[str] = []
    for filename, content in rendered.items():
        path = here / filename
        current = path.read_text() if path.is_file() else None
        if current == content:
            continue
        if args.write:
            path.write_text(content)
            print(f"regenerated {filename}")
        else:
            diff = difflib.unified_diff(
                (current or "").splitlines(),
                content.splitlines(),
                fromfile=filename,
                tofile=f"{filename} (from {TEMPLATE_NAME})",
                lineterm="",
            )
            print("\n".join(diff), file=sys.stderr)
            stale.append(filename)

    if stale:
        for filename in stale:
            print(f"{filename} is stale (re-run with --write).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
