CODE_BLOCK_PAT = "```\n{}\n```"
TRIPLE_BACKTICK = "```"
SYSTEM_REMINDER_TAG_OPEN = "<system-reminder>"
SYSTEM_REMINDER_TAG_CLOSE = "</system-reminder>"

# Tags format inspired by Anthropic and OpenCode
REMINDER_TAG_DESCRIPTION = f"""
# Reminder Tags
User messages may include {SYSTEM_REMINDER_TAG_OPEN} and {SYSTEM_REMINDER_TAG_CLOSE} tags.
These {SYSTEM_REMINDER_TAG_OPEN} tags contain useful information and reminders. \
They are automatically added by the system and are not actual user inputs.
Behave in accordance to these instructions if relevant, and continue normally if they are not.
""".strip()
