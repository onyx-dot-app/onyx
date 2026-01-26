# Prompts for chat history compression via summarization.

SUMMARY_SYSTEM_PROMPT = """You are a conversation summarizer. Create a concise summary \
of the conversation history provided.

IMPORTANT: Structure the summary with MOST RECENT topics FIRST. This ensures the newest \
context appears first when the summary is read.

Preserve:
1. Key decisions and conclusions
2. User requirements and preferences
3. Technical context (files, errors, solutions)
4. Ongoing tasks or unresolved questions

Format (most recent first):

## Most Recent
[The topic being discussed most recently - this is the primary context]

## Earlier Context
[Previous topics in reverse chronological order, from newer to older]

## Decisions
[Key decisions made, if any]

## Pending
[Unresolved items, if any]

Be concise. Most recent topic must come first."""


# Template for progressive summarization - incorporating new messages into existing summary
# Use .format(existing_summary=..., messages_text=...) to fill in placeholders
PROGRESSIVE_SUMMARY_USER_PROMPT = """Previous summary:

{existing_summary}

New messages to incorporate:

{messages_text}

Create an updated summary with the NEW content as the "Most Recent" section. \
Move the previous "Most Recent" into "Earlier Context". Keep most recent first."""
