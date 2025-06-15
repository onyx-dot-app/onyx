import json
import pandas as pd
from typing import List
from deepeval.test_case import LLMTestCase


def load_test_cases_from_csv(file_path: str) -> List[LLMTestCase]:
    """
    Reads a CSV file and creates LLMTestCases.

    It expects the CSV to have a 'response' column containing a JSON string.
    This JSON should contain 'answer' and 'top_documents'.
    It also expects 'query' and optionally 'golden_answer' columns.

    Args:
        file_path: The path to the CSV file.

    Returns:
        A list of LLMTestCase objects.
    """
    df = pd.read_csv(file_path)
    # 1. Define a function to safely parse the JSON in the 'response' column
    def parse_response_column(response_str: str):
        try:
            # Load the string as a JSON object
            response_json = json.loads(response_str)
            # Extract 'answer' and 'top_documents', providing defaults if they're missing
            answer = response_json.get('answer', '')
            top_docs = response_json.get('docs').get('top_documents', [])
            retrieval_context = []
            for doc in top_docs:
                retrieval_context.append(json.dumps(doc))
            return answer, retrieval_context
        except (json.JSONDecodeError, TypeError):
            # Return defaults if the string is not valid JSON or not a string
            return '', []

    # 2. Apply the parsing function to the 'response' column.
    # This creates a temporary DataFrame with 'parsed_answer' and 'parsed_context' columns.
    parsed_data = df['response'].apply(lambda r: pd.Series(parse_response_column(r)))
    parsed_data.columns = ['answer', 'top_documents']

    # 3. Join the parsed data back to the original DataFrame
    df = df.join(parsed_data)

    # 4. Handle the 'golden_answer' column (optional)
    if 'golden_answer' not in df.columns:
        df['golden_answer'] = ""
    else:
        df['golden_answer'] = df['golden_answer'].fillna('')

    # 5. Create the list of LLMTestCase objects
    return [
        LLMTestCase(
            input=row.query,
            actual_output=row.answer,       # Use the parsed answer
            expected_output=row.golden_answer,
            retrieval_context=row.top_documents,  # Use the parsed documents
            context=row.top_documents
        )
        for row in df.itertuples()
    ]
