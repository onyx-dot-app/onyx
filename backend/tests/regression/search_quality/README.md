# Search Quality Test Script

This Python script evaluates the search results for a list of queries.

This script will likely get refactored in the future as an API endpoint.
In the meanwhile, it is used to evaluate the search quality using locally ingested documents.
The key differentating factor with `answer_quality` is that it can evaluate results without explicit "ground truth" using the reranker as a reference.

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
   - `question_keyword: Optional[str]` modified query specifically for the retriever
   - `ground_truth: Optional[list[GroundTruth]]` a ranked list of expected search results with fields:
      - `doc_source: str` document source (e.g., Web, Drive, Linear), currently unused
      - `doc_link: str` link associated with document, used to find corresponding document in local index
   - `categories: Optional[list[str]]` list of categories, used to aggregate evaluation results

6. Copy `search_eval_config.yaml.template` to `search_eval_config.yaml` and specify the search and eval parameters

7. Run `run_search_eval.py` to run the search and evaluate the search results

```
python run_search_eval.py
```

8. Optionally, save the generated `test_queries.json` in the export folder to reuse the generated `question_keyword`, and rerun the search with alternative search parameters.

## Metrics
TODO:
Talk about how eval is handled without grounded docs

- Jaccard Similarity: the ratio between the intersect and the union between the topk search and rerank results. Higher is better
- Average Rank Change: The average absolute rank difference of the topk reranked chunks vs the entire search chunks. Lower is better
- Average Missing Chunk Ratio: The number of chunks in the topk reranked chunks not in the topk search chunks, over topk. Lower is better

Note that all of these metrics are affected by very narrow search results.
E.g., if topk is 20 but there is only 1 relevant document, the other 19 documents could be ordered arbitrarily, resulting in a lower score.


To address this limitation, there are score adjusted versions of the metrics.
The score adjusted version does not use a fixed topk, but computes the optimum topk based on the rerank scores.
This generally works in determining how many documents are relevant, although note that this approach isn't perfect.