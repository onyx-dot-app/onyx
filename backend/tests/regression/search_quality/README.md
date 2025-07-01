# Search Quality Test Script

This Python script evaluates the search results for a list of queries.

This script will likely get refactored in the future as an API endpoint.
In the meanwhile, it is used to evaluate the search quality using locally ingested documents.

## Usage

1. Ensure you have the required dependencies installed and onyx running. Note that auth must be disabled for this script to work (`AUTH_TYPE=disabled`, which is the case by default).

2. Set up the PYTHONPATH permanently:
   Add the following line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):
   ```
   export PYTHONPATH=$PYTHONPATH:/path/to/onyx/backend
   ```
   Replace `/path/to/onyx` with the actual path to your Onyx repository.
   After adding this line, restart your terminal or run `source ~/.bashrc` (or the appropriate config file) to apply the changes.

3. Navigate to Onyx repo, **search_quality** folder:

```
cd path/to/onyx/backend/tests/regression/search_quality
```

4. Copy `test_queries.json.template` to `test_queries.json` and add/remove test queries in it. The possible fields are:

   - `question: str` the query
   - `question_search: Optional[str]` modified query specifically for the search step
   - `ground_truth: Optional[list[GroundTruth]]` a ranked list of expected search results with fields:
      - `doc_source: str` document source (e.g., web, google_drive, linear), used to normalize links in some cases
      - `doc_link: str` link associated with document, used to find corresponding document in local index
   - `categories: Optional[list[str]]` list of categories, used to aggregate evaluation results

5. Run `run_search_eval.py` to evaluate the queries.  All parameters are optional and have sensible defaults:

```
python run_search_eval.py
  -d --dataset          # Path to the test-set JSON file (default: ./test_queries.json)
  -n --num_search       # Maximum number of search results to check per query (default: 50)
  -a --num_answer       # Maximum number of search results to use for answer evaluation (default: 25)
  -w --workers          # Number of parallel search requests (default: 10)
  -q --timeout          # Request timeout in seconds (default: 120)
  -e --api_endpoint     # Base URL of the Onyx API server (default: http://127.0.0.1:8080)
  -s --search_only      # Only perform search and not answer evaluation (default: false)
  -r --rerank_all       # Always rerank all search results (default: false)
  -t --tenant_id        # Tenant ID to use for the evaluation (default: None)
```

6. After the run an `eval-YYYY-MM-DD-HH-MM-SS` folder is created containing:

   * `test_queries.json`   – the dataset used with the indexed ground truth documents.
   * `search_results.json` – per-query details.
   * `results_by_category.csv` – aggregated metrics per category and for "all".
   * `search_position_chart.png` – bar-chart of ground-truth ranks.

You can copy the generated `test_queries.json` back to the root folder to skip the ground truth documents search step.