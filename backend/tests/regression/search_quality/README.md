# Search Quality Test Script

This Python script evaluates the search results for a list of queries.

This script will likely get refactored in the future as an API endpoint.
In the meanwhile, it is used to evaluate the search quality using locally ingested documents.
The key differentiating factor with `answer_quality` is that it can evaluate results without explicit "ground truth" using the reranker as a reference.

## Usage

1. Ensure you have the required dependencies installed and onyx running.

2. Ensure a reranker model is configured in the search settings.
This can be checked/modified by opening the admin panel, going to search settings, and ensuring a reranking model is set.

3. Set up the PYTHONPATH permanently:
   Add the following line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):
   ```
   export PYTHONPATH=$PYTHONPATH:/path/to/onyx/backend
   ```
   Replace `/path/to/onyx` with the actual path to your Onyx repository.
   After adding this line, restart your terminal or run `source ~/.bashrc` (or the appropriate config file) to apply the changes.

4. Navigate to Onyx repo, search_quality folder:

```
cd path/to/onyx/backend/tests/regression/search_quality
```

5. Copy `test_queries.json.template` to `test_queries.json` and add/remove test queries in it. The possible fields are:

   - `question: str` the query
   - `question_search: Optional[str]` modified query specifically for the search step
   - `ground_truth: Optional[list[GroundTruth]]` a ranked list of expected search results with fields:
      - `doc_source: str` document source (e.g., Web, Drive, Linear), currently unused
      - `doc_link: str` link associated with document, used to find corresponding document in local index
   - `categories: Optional[list[str]]` list of categories, used to aggregate evaluation results

6. Copy `search_eval_config.yaml.template` to `search_eval_config.yaml` and specify the search and eval parameters

7. Run `run_search_eval.py` to run the search and evaluate the search results

```
python run_search_eval.py
```

8. Optionally, save the generated `test_queries.json` in the export folder to reuse the generated `question_search`, and rerun the search evaluation with alternative search parameters.

## Metrics
There are two main metrics currently implemented:
- ratio_topk: the ratio of documents in the comparison set that are in the topk search results (higher is better, 0-1)
- avg_rank_delta: the average rank difference between the comparison set and search results (lower is better, 0-inf)

Ratio topk gives a general idea on whether the most relevant documents are appearing first in the search results. Decreasing `eval_topk` will make this metric stricter, requiring relevant documents to appear in a narrow window.

Avg rank delta is another metric which can give insight on the performance of documents not in the topk search results. If none of the comparison documents are in the topk, `ratio_topk` will only show a 0, whereas `avg_rank_delta` will show a higher value the worse the search results gets.

Furthermore, there are two versions of the metrics: ground truth, and soft truth.

The ground truth includes documents explicitly listed as relevant in the test dataset. The ground truth metrics will only be computed if a ground truth set is provided for the question and exists in the index.

The soft truth is built on top of the ground truth (if provided), filling the remaining entries with results from the reranker. The soft truth metrics will only be computed if `skip_rerank` is false. Computing the soft truth metric can be extremely slow, especially for large `num_returned_hits`. However, it can provide a good basis when there are many relevant documents in no particular order, or for running quick tests without explicitly having to mention which documents are relevant.