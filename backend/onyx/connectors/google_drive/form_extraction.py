from typing import Any


def _question_lines(question: dict[str, Any]) -> list[str | None]:
    lines: list[str | None] = [question.get("rowQuestion", {}).get("title")]
    choice: dict[str, Any] = question.get("choiceQuestion", {})
    lines.extend(
        f"- {option['value']}"
        for option in choice.get("options", [])
        if option.get("value")
    )
    scale: dict[str, Any] = question.get("scaleQuestion", {})
    lines.extend([scale.get("lowLabel"), scale.get("highLabel")])
    return lines


def get_form_text(form: dict[str, Any]) -> str:
    """The text of a Forms API form: its title, description, and each item
    with its choices. Responses are not part of a form."""
    info: dict[str, Any] = form.get("info", {})
    lines: list[str | None] = [info.get("title"), info.get("description")]
    for item in form.get("items", []):
        lines.extend([item.get("title"), item.get("description")])
        question: dict[str, Any] | None = item.get("questionItem", {}).get("question")
        group: dict[str, Any] = item.get("questionGroupItem", {})
        for q in [question] if question else group.get("questions", []):
            lines.extend(_question_lines(q))
        # A grid group's columns are the choices for each of its rows.
        if columns := group.get("grid", {}).get("columns"):
            lines.extend(_question_lines({"choiceQuestion": columns}))
        lines.append(item.get("videoItem", {}).get("caption"))
    return "\n".join(line for line in lines if line)
