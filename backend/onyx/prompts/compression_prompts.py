# Prompts for chat history compression via summarization.

# Cutoff marker helps the LLM focus on summarizing only messages before this point.
# This improves "needle in haystack" accuracy by explicitly marking where to stop.
SUMMARIZATION_CUTOFF_MARKER = (
    "<context_cutoff>"
    "Stop summarizing the rest of the conversation past this point."
    "</context_cutoff>"
)

SUMMARIZATION_PROMPT = """
You are a summarization system. Your task is to produce a detailed and accurate
summary of a chat conversation up to a specified cutoff message. The cutoff will
be marked by the string `<context_cutoff>`.

# Guidelines
- Only consider messages that occur at or before the cutoff point.
  Use the messages after it purely as context without including any of it in the summary.
- Preserve factual correctness and intent; do not infer or speculate.
- The summary should be information dense and detailed.
- The summary should be in paragraph format and long enough to capture all of the
  most prominent details.
- IMPORTANT: Structure the summary in reverse chronological order, with the MOST RECENT
  topics FIRST. This ensures the newest context appears first when the summary is read.

# Focus on:
- Key topics discussed (most recent first)
- Decisions made, tools used, and conclusions reached
- Open questions or unresolved items
- Important constraints, preferences, or assumptions stated
- Preserve question/answer pairs - keep the connection between user questions and
  assistant responses
- Omit small talk, repetition, and stylistic filler unless it affects meaning
""".strip()


USER_FINAL_REMINDER = """
Help summarize the conversation up to the cutoff point. It should be a long form
summary of the conversation up to the cutoff point as marked by `<context_cutoff>`.
Be thorough. Present topics in reverse chronological order (most recent first).
Preserve question/answer pairs.
""".strip()


# Template for progressive summarization content - existing summary + new messages
# Use .format(existing_summary=...) to fill in.
# Code appends messages and PROGRESSIVE_USER_REMINDER.
PROGRESSIVE_SUMMARY_PROMPT = """
Previous summary to build upon:

{existing_summary}

New messages to incorporate:
""".strip()


PROGRESSIVE_USER_REMINDER = """
Update the existing summary by incorporating the new messages up to the cutoff point.
Merge new information with existing context while maintaining reverse chronological
order (most recent first). Preserve question/answer pairs. Be thorough.
""".strip()
