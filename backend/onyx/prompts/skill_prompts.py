from onyx.tools.constants import SKILLS_LIST_TOOL_NAME, SKILLS_READ_TOOL_NAME

SKILLS_CATALOG_PROMPT = f"""<skills_instructions>
## Skills
A skill is a set of instructions for a task, stored in a SKILL.md file. Below \
is the list of skills that you can use. Each entry has a name and a description.

### Available skills
{{skills}}

### How to use skills
- Trigger rules: If the user names a skill OR the task clearly matches a \
skill's description shown above, you must use that skill for that turn. A \
skill the user picked for a message comes right before it in a <skill> \
block. Multiple mentions mean use them all. Do not carry skills across turns \
unless they are mentioned again.
- Missing or blocked: If a named skill is not in the list or cannot be read, \
say so briefly and continue with the best fallback. If the list says that \
skills were omitted, call `{SKILLS_LIST_TOOL_NAME}` to see all of them.
- How to use a skill (progressive disclosure):
  1) After you decide to use a skill, call `{SKILLS_READ_TOOL_NAME}` with its \
name and read its SKILL.md completely before you take task actions. A skill \
that is already in a <skill> block is loaded; do not read it again.
  2) You cannot open the other files of a skill or run its scripts. Follow \
its instructions as far as your tools allow, and tell the user when a step \
needs a bundled file or script.
  3) Do not delegate reading, summarizing, or interpreting skill instructions \
to a subagent.
- Coordination and sequencing: If multiple skills apply, choose the minimal \
set that covers the request and use them in order. Announce which skill(s) \
you are using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene: Read only the skills that you need.
</skills_instructions>"""

SKILLS_OMITTED_LINE = (
    "- {count} additional {skills} omitted from this bounded skills list."
)

MENTIONED_SKILL_PROMPT = """<skill>
<name>{name}</name>
{instructions}
</skill>"""

MENTIONED_SKILL_TRUNCATED_NOTE = f"""

[SKILL.md continues. Call `{SKILLS_READ_TOOL_NAME}` with name="{{name}}" and \
start_char={{start_char}} to read the rest.]"""

MENTIONED_SKILL_UNAVAILABLE = (
    "This skill is no longer available, so its instructions cannot be loaded. "
    "Tell the user if the request depends on it."
)
