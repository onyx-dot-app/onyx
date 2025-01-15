PERSONA_CATEGORY_GENERATION_PROMPT = """
Based on the assistant's name, description, and instructions, generate {num_categories}
 **unique and diverse** categories that represent different types of starter messages a user
 might send to initiate a conversation with this chatbot assistant.

**Ensure that the categories are relevant and cover
topics related to the assistant's capabilities.**

Provide the categories as a JSON array of strings **without any code fences or additional text**.

**Context about the assistant:**
- **Name**: {name}
- **Description**: {description}
- **Instructions**: {instructions}
"""

PERSONA_STARTER_MESSAGE_CREATION_PROMPT = """
Create a starter message that a **user** might send to initiate a conversation with a chatbot assistant.

{category_prompt}

Your response should only include the actual message that the user would send to the assistant.
This should be natural, engaging, and encourage a helpful response from the assistant.
**Avoid overly specific details; keep the message general and broadly applicable.**

For example:
- Instead of "I've just adopted a 6-month-old Labrador puppy who's pulling on the leash,"
write "I'm having trouble training my new puppy to walk nicely on a leash."
Do not provide any additional text or explanation and be extremely concise

**Context about the assistant:**
- **Name**: {name}
- **Description**: {description}
- **Instructions**: {instructions}
""".strip()


def format_persona_starter_message_prompt(
    name: str, description: str, instructions: str, category: str | None = None
) -> str:
    category_prompt = f"**Category**: {category}" if category else ""
    return PERSONA_STARTER_MESSAGE_CREATION_PROMPT.format(
        category_prompt=category_prompt,
        name=name,
        description=description,
        instructions=instructions,
    )


if __name__ == "__main__":
    print(PERSONA_CATEGORY_GENERATION_PROMPT)
    print(PERSONA_STARTER_MESSAGE_CREATION_PROMPT)
