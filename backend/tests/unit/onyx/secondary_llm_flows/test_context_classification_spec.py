"""The classification prompts and their parsing specs must stay in sync.

Nothing else enforces this join. A category added to a prompt without a
`situation_to_type` entry (or the reverse) fails silently: the LLM answers with
a number the parser maps to the default. The prompt bodies stay hand-written on
purpose - the two prompts diverge in their examples and decision notes - so
this test guards the join instead of generating it.
"""

import re

import pytest

from onyx.secondary_llm_flows.document_filter import (
    _CODE_CONTEXT_SPEC,
    _TEXT_CONTEXT_SPEC,
    _ContextClassificationSpec,
)

# "**3 - FULL_FILE**" - one classification category heading.
_CATEGORY_PATTERN = re.compile(r"^\*\*(\d+) - (\w+)\*\*", re.MULTILINE)
# The digits the prompt offers, e.g. "... most applicable (0, 1, 2, 3, or 4)."
_TRAILER_PATTERN = re.compile(r"ONLY output the NUMBER[^(]*\(([^)]*)\)")

_SPECS: dict[str, _ContextClassificationSpec] = {
    "text": _TEXT_CONTEXT_SPEC,
    "code": _CODE_CONTEXT_SPEC,
}


@pytest.mark.parametrize("spec_name", sorted(_SPECS))
def test_prompt_categories_match_situation_map(spec_name: str) -> None:
    """Every prompt category maps to an expansion type, and vice versa."""
    spec = _SPECS[spec_name]
    categories = _CATEGORY_PATTERN.findall(spec.prompt_template)
    assert categories, "no '**N - NAME**' categories found in the prompt"

    numbers = [int(number) for number, _name in categories]
    assert numbers == sorted(numbers), "prompt categories are out of order"
    assert set(numbers) == set(spec.situation_to_type), (
        "prompt categories and situation_to_type disagree"
    )

    labels = {int(number): name for number, name in categories}
    for situation, expansion_type in spec.situation_to_type.items():
        assert labels[situation] == expansion_type.name, (
            f"category {situation} is labelled {labels[situation]} "
            f"but maps to {expansion_type.name}"
        )


@pytest.mark.parametrize("spec_name", sorted(_SPECS))
def test_prompt_trailer_offers_every_situation(spec_name: str) -> None:
    """The digits the prompt tells the LLM to choose from are the mapped ones."""
    spec = _SPECS[spec_name]
    trailer = _TRAILER_PATTERN.search(spec.prompt_template)
    assert trailer, "prompt has no 'ONLY output the NUMBER ... (...)' trailer"

    offered = {int(digit) for digit in re.findall(r"\d+", trailer.group(1))}
    assert offered == set(spec.situation_to_type)


@pytest.mark.parametrize("spec_name", sorted(_SPECS))
def test_situations_are_contiguous(spec_name: str) -> None:
    """situation_pattern is a [min-max] range, so a gap would admit a digit
    that maps to nothing and silently become the default."""
    situations = sorted(_SPECS[spec_name].situation_to_type)
    assert situations == list(range(situations[0], situations[-1] + 1))
    # Single-digit range: the pattern cannot match a two-digit answer either.
    assert all(0 <= situation <= 9 for situation in situations)
