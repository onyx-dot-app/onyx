import argparse
import os
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from openai import OpenAI


ASSISTANT_NAME = "Topic Analyzer"
SYSTEM_PROMPT = """
You are a helpful assistant that analyzes topics by searching through available \
documents and providing insights. These available documents come from common \
workplace tools like Slack, emails, Confluence, Google Drive, etc.

When analyzing a topic:
1. Search for relevant information using the search tool
2. Synthesize the findings into clear insights
3. Highlight key trends, patterns, or notable developments
4. Maintain objectivity and cite sources where relevant
"""
USER_PROMPT = """
Please analyze and provide insights about this topic: {topic}.

IMPORTANT: do not mention things that are not relevant to the specified topic. \
If there is no relevant information, just say "No relevant information found."
"""


def wait_on_run(client: OpenAI, run, thread):  # type: ignore
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        time.sleep(0.5)
    return run


def show_response(messages) -> None:  # type: ignore
    # Get only the assistant's response text
    for message in messages.data[::-1]:
        if message.role == "assistant":
            for content in message.content:
                if content.type == "text":
                    print(content.text)
                    break


def analyze_topics(topics: list[str]) -> None:
    openai_api_key = os.environ.get(
        "OPENAI_API_KEY", "<your OpenAI API key if not set as env var>"
    )
    onyx_api_key = os.environ.get(
        "DANSWER_API_KEY", "<your Onyx API key if not set as env var>"
    )
    client = OpenAI(
        api_key=openai_api_key,
        base_url="http://localhost:8080/openai-assistants",
        default_headers={
            "Authorization": f"Bearer {onyx_api_key}",
        },
    )

    # Create an assistant if it doesn't exist
    try:
        assistants = client.beta.assistants.list(limit=100)
        # Find the Topic Analyzer assistant if it exists
        assistant = next((a for a in assistants.data if a.name == ASSISTANT_NAME))
        client.beta.assistants.delete(assistant.id)
    except Exception:
        pass

    assistant = client.beta.assistants.create(
        name=ASSISTANT_NAME,
        instructions=SYSTEM_PROMPT,
        tools=[{"type": "SearchTool"}],  # type: ignore
        model="gpt-4o",
    )

    # Process each topic individually
    for topic in topics:
        thread = client.beta.threads.create()
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=USER_PROMPT.format(topic=topic),
        )

        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id,
            tools=[
                {  # type: ignore
                    "type": "SearchTool",
                    "retrieval_details": {
                        "run_search": "always",
                        "filters": {
                            "time_cutoff": str(
                                datetime.now(timezone.utc) - timedelta(days=7)
                            )
                        },
                    },
                }
            ],
        )

        run = wait_on_run(client, run, thread)
        messages = client.beta.threads.messages.list(
            thread_id=thread.id, order="asc", after=message.id
        )
        print(f"\nAnalysis for topic: {topic}")
        print("-" * 40)
        show_response(messages)
        print()


# Example usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze specific topics")
    parser.add_argument("topics", nargs="+", help="Topics to analyze (one or more)")

    args = parser.parse_args()
    analyze_topics(args.topics)
