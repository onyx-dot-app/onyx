# Search Quality Test Script

This Python script evaluates the search results for a list of queries.

Unlike the script in answer_quality, this script is much less customizable and runs using currently ingested documents, though it allows for quick testing of search parameters on a bunch of test queries that don't have well-defined answers.

## Usage

1. Ensure you have the required dependencies installed.
2. Configure the `search_eval_config.yaml` to specify the access user and search parameters
3. Set up the PYTHONPATH permanently:
   Add the following line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):
   ```
   export PYTHONPATH=$PYTHONPATH:/path/to/onyx/backend
   ```
   Replace `/path/to/onyx` with the actual path to your Onyx repository.
   After adding this line, restart your terminal or run `source ~/.bashrc` (or the appropriate config file) to apply the changes.
4. Navigate to Onyx repo:

```
cd path/to/onyx
```

5. Navigate to the search_quality folder:

```
cd backend/tests/regression/search_quality
```

6. Run the eval script

```
python run_search_eval.py
```
