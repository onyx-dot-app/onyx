from typing import Any

from agents.models.openai_responses import Converter as OpenAIResponsesConverter


# TODO: I am very sad that I have to monkey patch this :(
# Basically, OpenAI agents sdk doesn't convert the tool choice correctly
# when they have a built-in tool in their framework, like they do for web_search.
# Going to open up a thread with OpenAI agents team to see what they recommend
# or what we can fix.
# A discussion is warranted, but we likely want to just write our own LitellmModel for
# the OpenAI agents SDK since they probably don't really care about Litellm and will
# prioritize functionality for their own models.
def monkey_patch_convert_tool_choice_to_ignore_openai_hosted_web_search() -> None:
    if (
        getattr(OpenAIResponsesConverter.convert_tool_choice, "__name__", "")
        == "_patched_convert_tool_choice"
    ):
        return

    orig_func = OpenAIResponsesConverter.convert_tool_choice.__func__  # type: ignore[attr-defined]

    def _patched_convert_tool_choice(cls: type, tool_choice: Any) -> Any:
        if tool_choice == "web_search":
            return {"type": "function", "name": "web_search"}
        return orig_func(cls, tool_choice)

    OpenAIResponsesConverter.convert_tool_choice = classmethod(  # type: ignore[method-assign, assignment]
        _patched_convert_tool_choice
    )
