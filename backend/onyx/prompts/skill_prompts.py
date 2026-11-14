from onyx.tools.constants import SKILLS_LIST_TOOL_NAME, SKILLS_READ_TOOL_NAME

# Codex's skills instructions, without file paths, root aliases, bundled files
# or scripts, which chat cannot open.
SKILLS_CATALOG_PROMPT = f"""<skills_instructions>
## Skills
A skill is a set of instructions provided through a `SKILL.md` source. Below \
is the list of skills that can be used. Each entry includes a name and \
description.
### Available skills
{{skills}}
### How to use skills
- Discovery: The list above is the skills available in this session (name + \
description). Read a skill's `SKILL.md` with `{SKILLS_READ_TOOL_NAME}`. If the \
list says that skills were omitted, call `{SKILLS_LIST_TOOL_NAME}` to see all \
of them.
- Trigger rules: If the user names a skill (with `@` or plain text) OR the \
task clearly matches a skill's description shown above, you must use that \
skill for that turn. A skill the user picked for a message follows that \
message in a <skill> block. Multiple mentions mean use them all. Do not carry \
skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or its `SKILL.md` can't \
be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, the main agent must read its `SKILL.md` \
completely before taking task actions: call `{SKILLS_READ_TOOL_NAME}` with its \
name. If `{SKILLS_READ_TOOL_NAME}` says the file continues, call it again with \
`start_char` until the end. A skill in a <skill> block is already loaded; do \
not read it again unless its block says it continues.
  2) You cannot open the other files of a skill or run its scripts. Follow its \
instructions as far as your tools allow, and tell the user when a step needs a \
bundled file or script.
  3) The main agent must read each selected skill itself before acting on it. \
Do not delegate reading, summarizing, or interpreting skill instructions to a \
subagent. Subagents may still perform task work when the selected skill allows \
it.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request \
and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip \
an obvious skill, say why.
- Context hygiene:
  - Progressive disclosure applies to selecting relevant files, not partially \
reading a selected instruction file. Do not load unrelated skills.
  - Avoid deep reference-chasing: prefer reading only the skills the request \
names or clearly needs unless you're blocked.
  - When variants exist (frameworks, providers, domains), pick only the \
relevant skill(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (unclear \
instructions, a step needs a file or script you cannot open), state the issue, \
pick the next-best approach, and continue.
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
