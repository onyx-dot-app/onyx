"""Constants for document editor tests."""

SAMPLE_DOCUMENT = """
<html>
<body>
<h1>Sample Document</h1>
<p>This is a sample document.</p>
</body>
</html>
"""

SAMPLE_INSTRUCTIONS = """
1. Change the title to "Modified Article"
2. Add a new paragraph after the first paragraph
3. Remove the third list item
"""

EXPECTED_EDITED_DOCUMENT = """
<html>
<body>
<h1>Modified Article</h1>
<p>This is a sample document.</p>
<p>This is a new paragraph.</p>
</body>
</html>
"""

LARGE_DOCUMENT = """
<html>
<body>
    <h1>Product Specifications</h1>
    <section>
        <h2>Materials</h2>
        <p>The product is made from high-quality plastic components that ensure durability and longevity.</p>
        <p>All parts are certified for safety and environmental compliance.</p>
        <ul>
            <li>Main body:</li>
            <li>Connectors:</li>
            <li>Mounting brackets:</li>
        </ul>
    </section>
    <section>
        <h2>Features</h2>
        <p>The construction allows for easy maintenance and cleaning.</p>
        <p>All surfaces are treated with a special coating for enhanced durability.</p>
    </section>
</body>
</html>
"""

WORD_REPLACEMENT_INSTRUCTIONS = (
    "Change all instances of the word 'plastic' to 'metal' in the document."
)


def get_default_llm():
    """Get a default LLM instance for testing.

    Returns:
        DefaultMultiLLM: A configured LLM instance for testing.

    Raises:
        ValueError: If OPENAI_API_KEY is not set in environment variables.
    """
    import os

    from onyx.llm.chat_llm import DefaultMultiLLM

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in environment variables")

    return DefaultMultiLLM(
        model_provider="openai",
        model_name="gpt-4",  # Using GPT-4 for better reliability
        temperature=0.0,
        api_key=api_key,
        max_input_tokens=10000,
    )
