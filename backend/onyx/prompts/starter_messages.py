PERSONA_CATEGORY_GENERATION_PROMPT = """
Based on the assistant's name, description, and instructions, generate a list of {num_categories}
 **unique and diverse** categories that represent different types of starter messages a user
 might send to initiate a conversation with this chatbot assistant.

**Ensure that the categories are varied and cover a wide range of topics related to the assistant's capabilities.**

Provide the categories as a JSON array of strings **without any code fences or additional text**.

**Context about the assistant:**
- **Name**: {name}
- **Description**: {description}
- **Instructions**: {instructions}
""".strip()

PERSONA_STARTER_MESSAGE_CREATION_PROMPT = """
Create a starter message that a **user** might send to initiate a conversation with a chatbot assistant.

**Category**: {category}

Your response should include two parts:

1. **Title**: A short, engaging title that reflects the user's intent
   (e.g., 'Need Travel Advice', 'Question About Coding', 'Looking for Book Recommendations').

2. **Message**: The actual message that the user would send to the assistant.
   This should be natural, engaging, and encourage a helpful response from the assistant.
   **Avoid overly specific details; keep the message general and broadly applicable.**

For example:
- Instead of "I've just adopted a 6-month-old Labrador puppy who's pulling on the leash,"
write "I'm having trouble training my new puppy to walk nicely on a leash."

Ensure each part is clearly labeled and separated as shown above.
Do not provide any additional text or explanation and be extremely concise

**Context about the assistant:**
- **Name**: {name}
- **Description**: {description}
- **Instructions**: {instructions}
""".strip()


if __name__ == "__main__":
    print(PERSONA_CATEGORY_GENERATION_PROMPT)
    print(PERSONA_STARTER_MESSAGE_CREATION_PROMPT)
