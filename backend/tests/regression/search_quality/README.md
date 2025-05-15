# Search Quality Test Script

This Python script evaluates the search results for a list of queries.

Unlike the script in answer_quality, this script is much less customizable and runs using currently ingested documents, though it allows for quick testing of search parameters on a bunch of test queries that don't have well-defined answers.

## Usage

1. Ensure you have the required dependencies installed.
2. Set up the PYTHONPATH permanently:
   Add the following line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):
   ```
   export PYTHONPATH=$PYTHONPATH:/path/to/onyx/backend
   ```
   Replace `/path/to/onyx` with the actual path to your Onyx repository.
   After adding this line, restart your terminal or run `source ~/.bashrc` (or the appropriate config file) to apply the changes.
3. Navigate to Onyx repo, search_quality folder:

```
cd path/to/onyx/backend/tests/regression/search_quality
```

4. Copy `search_queries.json.template` to `search_queries.json` and add/remove test queries in it
5. Run `generate_search_queries.py` to generate the modified queries for the search pipeline

```
python generate_search_queries.py
```

6. Copy `search_eval_config.yaml.template` to `search_eval_config.yaml` and specify the search and eval parameters
7. Run `run_search_eval.py` to evaluate the search results against the reranked results

```
python run_search_eval.py
```

8. Repeat steps 6 and 7 to test and compare different search parameters