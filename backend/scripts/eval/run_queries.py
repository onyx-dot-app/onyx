"""
Run Queries on Onyx API

This script processes queries through the Onyx API and creates a new CSV file with responses.
It can be used for batch evaluation of queries or testing purposes.

Example Usage:
    Basic usage with default settings:
        python eval/run_queries.py queries.csv results.csv --auth_cookie "AUTH_COOKIE_VALUE"
    
    Only retrieve documents without generating answers:
        python eval/run_queries.py queries.csv results.csv --only_retrieve_docs
    
    Use custom URL and authentication:
        python eval/run_queries.py queries.csv results.csv --url_prefix "http://myserver:8000" --auth_cookie "custom_cookie_value"
    
    Full command with all options:
        python eval/run_queries.py queries.csv results.csv --only_retrieve_docs --url_prefix "http://localhost:3000" --auth_cookie "fastapiusersauth=xyz123"

Input CSV Format:
    The input CSV should have the following columns:
        query,golden_answer
        "What is machine learning?","Machine learning is a subset of AI..."
        "How does neural networks work?","Neural networks are computing systems..."
        "Explain deep learning concepts","Deep learning is a subset of machine learning..."
    
Output Format:
    The script will create a new CSV file with the original columns plus a 'response' column:
        query,golden_answer,response
        "What is machine learning?","Machine learning is a subset of AI...","{\"answer\": \"...\", \"docs\": {...}}"
    
Requirements:
    - Onyx server running and accessible
    - Valid authentication cookie
    - Input CSV file with 'query' and 'golden_answer' columns
"""

import os
import sys
import requests
import json
import pandas as pd
import argparse

from ee.onyx.server.query_and_chat.models import OneShotQARequest
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import MessageType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import IndexFilters, RetrievalDetails


def get_response_for_query(
    query: str, only_retrieve_docs: bool, url_prefix: str, auth_cookie: str
) -> dict:
    filters = IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        access_control_list=None,
    )

    messages = [ThreadMessage(message=query, sender=None, role=MessageType.USER)]
    new_message_request = OneShotQARequest(
        messages=[msg.model_dump() for msg in messages],
        prompt_id=0,
        persona_id=0,
        retrieval_options=RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=True,
            filters=filters.model_dump(),
            enable_auto_detect_filters=False,
        ).model_dump(),
        return_contexts=True,
        skip_gen_ai_answer_generation=only_retrieve_docs,
    )

    url = url_prefix + "/api/query/answer-with-citation"
    headers = {
        'Content-Type': 'application/json',
        'Cookie': auth_cookie,
        'Origin': 'http://localhost:3000',
    }
    body = new_message_request.model_dump()
    body["user"] = None
    try:
        response = requests.post(url, headers=headers, json=body)
        return response.json()
    except Exception as e:
        print("Failed to answer the questions:")
        print(f"\t {str(e)}")
        raise e


def process_csv_queries(
    input_csv_path: str,
    output_csv_path: str,
    only_retrieve_docs: bool = False, 
    url_prefix: str = "http://localhost:3000", 
    auth_cookie: str = None,
) -> None:
    """
    Process queries from a CSV file and create a new CSV file with responses.
    
    Args:
        input_csv_path: Path to the input CSV file containing queries
        output_csv_path: Path to the output CSV file to create
        only_retrieve_docs: Whether to only retrieve docs without generating answers
        url_prefix: URL prefix for API requests
        auth_cookie: Authentication cookie for API requests
    """
    # Read the CSV file
    df = pd.read_csv(input_csv_path)
    
    # Validate required columns
    if 'query' not in df.columns:
        raise ValueError("CSV file must contain a 'query' column")
    
    # Add golden_answer column if it doesn't exist
    if 'golden_answer' not in df.columns:
        df['golden_answer'] = ""
    
    # Initialize response column
    responses = []
    
    for i, row in df.iterrows():
        query = row['query']
        print(f"Processing query {i+1}/{len(df)}: {query[:50]}...")
        
        try:
            response_json = get_response_for_query(query, only_retrieve_docs, url_prefix, auth_cookie)
            responses.append(json.dumps(response_json))
        except Exception as e:
            print(f"Error processing query '{query}': {str(e)}")
            responses.append(json.dumps({'error': str(e)}))
    
    # Add response column to dataframe
    df['response'] = responses
    
    # Save to new CSV file
    df.to_csv(output_csv_path, index=False)
    print(f"Added responses to {len(df)} queries and saved to {output_csv_path}")


def main():
    """Main function for command-line usage."""
    parser = argparse.ArgumentParser(description='Process queries from CSV using Onyx API and create new CSV with responses')
    
    parser.add_argument('input_csv', help='Path to input CSV file containing queries (must have "query" column)')
    parser.add_argument('output_csv', help='Path to output CSV file to create')
    parser.add_argument('--only_retrieve_docs', action='store_true', 
                        help='Only retrieve documents without generating answers')
    parser.add_argument('--url_prefix', default='http://localhost:3000', 
                        help='URL prefix for API requests')
    parser.add_argument('--auth_cookie', help='Authentication cookie for API requests')
    
    args = parser.parse_args()
    
    # Validate input CSV file exists
    if not os.path.exists(args.input_csv):
        print(f"Error: Input CSV file '{args.input_csv}' not found")
        sys.exit(1)
    
    try:
        # Process queries and create new CSV with responses
        process_csv_queries(
            input_csv_path=args.input_csv,
            output_csv_path=args.output_csv,
            only_retrieve_docs=args.only_retrieve_docs,
            url_prefix=args.url_prefix,
            auth_cookie=args.auth_cookie
        )
    except Exception as e:
        print(f"Error processing CSV: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
