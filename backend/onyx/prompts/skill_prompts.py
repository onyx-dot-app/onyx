# The skills instructions of chat: SKILL.md comes from the read
# tool, and the `Skill files:` line of a SKILL.md says where its other files
# are in the sandbox. The steps address the agent that reads the catalog,
# which can be a Deep Research research agent, and name the skill tools as
# that agent calls them.
SKILLS_CATALOG_PROMPT = """<skills_instructions>
## Skills
A skill is a set of instructions provided through a `SKILL.md` source. Below \
is the list of skills that can be used. Each entry includes a name and \
description.
### Available skills
{skills}
### How to use skills
- Discovery: The list above is the skills available in this session (name + \
description). Read a skill's `SKILL.md` with `{read_tool}`. If the \
list says that skills were omitted, call `{list_tool}` to see all \
of them.
- Trigger rules: If the user names a skill (with `@` or plain text) OR the \
task clearly matches a skill's description shown above, you must use that \
skill for that turn. A skill the user picked for a message follows that \
message in a <skill> block. Multiple mentions mean use them all. Do not carry \
skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or its `SKILL.md` can't \
be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, you must read its `SKILL.md` completely \
before taking task actions: call `{read_tool}` with its name, and act only \
after you have read its result. If `{read_tool}` says the file continues, \
call it again with `start_char` until the end. A skill in a <skill> block is \
already loaded; do not read it again unless its block says it continues.
  2) When a `SKILL.md` starts with a `Skill files:` line, the skill has other \
files, such as scripts, in the read-only folder that the line names. The line \
says how to use them. A skill without that line has no other files that you \
can open here: follow its instructions as far as your tools allow, and tell the user when a \
step needs a bundled file or script.
  3) Read each selected skill yourself before acting on it. Do not delegate \
reading, summarizing, or interpreting skill instructions to another agent. \
Agents you start may still perform task work when the selected skill allows it.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request \
and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip \
an obvious skill, say why.
- Context hygiene:
  - Progressive disclosure applies to selecting relevant files, not partially \
reading a selected instruction file. Do not load unrelated skills.
- Safety and fallback: If a skill can't be applied cleanly (unclear \
instructions, a step needs a file or script you cannot open), state the issue, \
pick the next-best approach, and continue.
</skills_instructions>"""

_SKILL_FILES_USE = (
    "Run its scripts with their interpreter, for example "
    "`python {folder}/scripts/<name>.py`. To change a file, copy the skill "
    "into your working directory first.\n\n"
)

# The sandbox gets the built-in skills at the turn's first sandbox call
# (file_copies.py:TurnSkillCopies).
BUILT_IN_SKILL_FILES_LINE = (
    "Skill files: {folder}/ (read-only), in the sandbox. A `[skills]` line on "
    "a tool result reports a copy of them in progress. " + _SKILL_FILES_USE
)

CUSTOM_SKILL_FILES_LINE = (
    "Skill files: {folder}/ (read-only). Call {load_tool} with this skill's "
    "name to copy them into the sandbox, then use them. " + _SKILL_FILES_USE
)

SKILLS_UNAVAILABLE_INTEGRATIONS_LINE = (
    "Some skills come from plugins that need integrations the user cannot use "
    "now: {names}. If a step needs one, tell the user to add it, turn it on or "
    "sign in under Customize > Integrations."
)

SKILLS_OMITTED_LINE = (
    "- {count} additional {skills} omitted from this bounded skills list."
)

MENTIONED_SKILL_PROMPT = """<skill>
<name>{name}</name>
{instructions}
</skill>"""

# Saved with the message, so it names no tool: the model that reads it can
# have another tool family.
MENTIONED_SKILL_TRUNCATED_NOTE = """

[SKILL.md continues. Read the rest of skill "{name}" from \
start_char={start_char}.]"""
