# ruff: noqa: E501, W605 start
USER_INFORMATION_HEADER = "\n# User Information\n\n"

BASIC_INFORMATION_PROMPT = """
## Basic Information
User name: {user_name}
User email: {user_email}{user_role}
""".lstrip()

# This line only shows up if the user has configured their role.
USER_ROLE_PROMPT = """
User role: {user_role}
""".lstrip()

# Team information should be a paragraph style description of the user's team.
TEAM_INFORMATION_PROMPT = """
## Team Information
{team_information}
""".lstrip()

# User preferences should be a paragraph style description of the user's preferences.
USER_PREFERENCES_PROMPT = """
## User Preferences
{user_preferences}
""".lstrip()

# User memories should look something like:
# - Memory 1
# - Memory 2
# - Memory 3
USER_MEMORIES_PROMPT = """
## User Memories
{user_memories}
""".lstrip()

# ruff: noqa: E501, W605 end
