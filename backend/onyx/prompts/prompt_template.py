import re

from onyx.prompts.prompt_utils import replace_current_datetime_tag


class PromptTemplate:
    """
    A class for building prompt templates with placeholders.
    Useful when building templates with json schemas, as {} will not work with f-strings.
    Unlike string.replace, this class will raise an error if the fields are missing.
    """

    DEFAULT_PATTERN = r"---([a-zA-Z0-9_]+)---"

    def __init__(self, template: str, pattern: str = DEFAULT_PATTERN):
        self._pattern_str = pattern
        self._pattern = re.compile(pattern)
        self._template = template
        self._fields: set[str] = set(self._pattern.findall(template))

    def build(self, **kwargs: str) -> str:
        """
        Build the prompt template with the given fields.
        Will raise an error if the fields are missing.
        Will ignore fields that are not in the template.
        """
        missing = self._fields - set(kwargs.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}.")
        built = self._replace_fields(kwargs)
        return self._postprocess(built)

    def partial_build(self, **kwargs: str) -> "PromptTemplate":
        """
        Returns another PromptTemplate with the given fields replaced.
        Will ignore fields that are not in the template.
        """
        new_template = self._replace_fields(kwargs)
        return PromptTemplate(new_template, self._pattern_str)

    def _replace_fields(self, field_vals: dict[str, str]) -> str:
        def repl(match: re.Match) -> str:
            key = match.group(1)
            return field_vals.get(key, match.group(0))

        return self._pattern.sub(repl, self._template)

    def _postprocess(self, text: str) -> str:
        """Apply global replacements such as [[CURRENT_DATETIME]]."""
        if not text:
            return text
        # Ensure [[CURRENT_DATETIME]] matches shared prompt formatting
        return replace_current_datetime_tag(
            text,
            full_sentence=True,
            include_day_of_week=True,
        )
