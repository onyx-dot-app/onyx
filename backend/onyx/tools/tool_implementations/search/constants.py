"""Constants for search tool implementations."""

# Query Expansion and Fusion Weights
# Taking an opinionated stance on the weights, no chance users can do a good job customizing this.
# The dedicated rephrased/extracted semantic query is likely the best for hybrid search
LLM_SEMANTIC_QUERY_WEIGHT = 1.3
# The semantic queries the model provides directly in the tool call.
MODEL_SEMANTIC_QUERY_WEIGHT = 1.0
# The keyword queries the model provides directly in the tool call. These provide more breadth
# through a different search ranking function and are likely to produce the most different results.
MODEL_KEYWORD_QUERY_WEIGHT = 1.0
# This is much lower weight because it is likely pretty similar to the LLM semantic query but just worse quality.
ORIGINAL_QUERY_WEIGHT = 0.5

# Hybrid Search Configuration
# NOTE: only used by the legacy Vespa document index; keyword queries from the search tool
# run as pure keyword (BM25) searches with hybrid_alpha=0.0.
KEYWORD_QUERY_HYBRID_ALPHA = 0.2
# Routes a query down the pure keyword (BM25) retrieval path — no embedding is computed.
KEYWORD_ONLY_HYBRID_ALPHA = 0.0

# Pagination
# How many rounds of deeper OpenSearch fetches a single paginate call may trigger when the
# in-memory cache doesn't cover the requested page.
MAX_PAGINATION_FALLBACK_ROUNDS = 2

# Reciprocal Rank Fusion
RRF_K_VALUE = 50

# Context Expansion
FULL_DOC_NUM_CHUNKS_AROUND = 5

# If a document is quite relevant and has many returned sections, likely it's enough to use the chunks around
# the highest scoring section to detect relevance. This allows more other docs to be evaluated in the step.
# This avoids documents with good titles or generally strong matches to flood out the rest of the search results.
# If there are multiple indepedent sections from the doc, this won't truncate it, only if they're connected.
MAX_CHUNKS_FOR_RELEVANCE = 3

# The token budget for the LLM relevance-selection step is
# max_llm_chunks * DOC_EMBEDDING_CONTEXT_SIZE * this multiplier. The selection step can
# afford to see more candidates than what is ultimately fed to the chat LLM since it only
# picks documents rather than reading them in full.
SELECTION_TOKEN_BUDGET_MULTIPLIER = 2
