# Search Quality Test Script

This Python script evaluates the search and answer quality for a list of queries, against a ground truth. It will use the currently ingested documents for the search, answer generation, and ground truth comparisons.

## Usage

1. Ensure you have the required dependencies installed and onyx running.

2. Ensure you have `OPENAI_API_KEY` set if you intend to do answer evaluation (enabled by default, unless you run the script with the `-s` flag). Also, if you're not using `AUTH_TYPE=disabled`, go to the API Keys page in the admin panel, generate a basic api token, and add it to the env file as `ONYX_API_KEY=on_...`.

3. Navigate to Onyx repo, **search_quality** folder:

```
cd path/to/onyx/backend/tests/regression/search_quality
```

4. Copy `test_queries.json.template` to `test_queries.json` and add/remove test queries in it. The fields for each query are:

   - `question: str` the query
   - `ground_truth: list[GroundTruth]` an un-ranked list of expected search results with fields:
      - `doc_source: str` document source (e.g., web, google_drive, linear), used to normalize the links in some cases
      - `doc_link: str` link associated with document, used to find corresponding document in local index
   - `ground_truth_response: Optional[str]` a response with clauses the ideal answer should include
   - `categories: Optional[list[str]]` list of categories, used to aggregate evaluation results

5. Run `run_search_eval.py` to evaluate the queries.  All parameters are optional and have sensible defaults:

```
python run_search_eval.py
  -d --dataset          # Path to the test-set JSON file (default: ./test_queries.json)
  -n --num_search       # Maximum number of documents to retrieve per search (default: 50)
  -a --num_answer       # Maximum number of documents to use for answer evaluation (default: 25)
  -w --max_workers      # Maximum number of concurrent search requests (0 = unlimited, default: 10).
  -r --max_req_rate     # Maximum number of search requests per minute (0 = unlimited, default: 0).
  -q --timeout          # Request timeout in seconds (default: 120)
  -e --api_endpoint     # Base URL of the Onyx API server (default: http://127.0.0.1:8080)
  -s --search_only      # Only perform search and not answer evaluation (default: false)
  -t --tenant_id        # Tenant ID to use for the evaluation (default: None)
```

Note: If you only care about search quality, you should run with the `-s` flag for a significantly faster evaluation. Furthermore, you should set `-r` to 1 if running with federated search enabled to avoid hitting rate limits.

6. After the run, an `eval-YYYY-MM-DD-HH-MM-SS` folder is created containing:

   * `test_queries.json`   – the dataset used with the list of valid queries and corresponding indexed ground truth.
   * `search_results.json` – per-query search and answer details.
   * `results_by_category.csv` – aggregated metrics per category and for "all".
   * `search_position_chart.png` – bar-chart of ground-truth ranks.

You can replace `test_queries.json` with the generated one for a slightly faster loading of the queries the next time around.