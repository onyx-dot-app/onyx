"""Constants for search tool implementations."""

# Query Expansion and Fusion Weights
# Taking an opinionated stance on the weights, no chance users can do a good job customizing this.
# The dedicated rephrased/extracted semantic query is likely the best for hybrid search
LLM_SEMANTIC_QUERY_WEIGHT = 1.3
# The keyword expansions provide more breadth through a different search ranking function
# This one is likely to produce the most different results.
LLM_KEYWORD_QUERY_WEIGHT = 1.0
# This is also lower because it is the LLM generated query without the custom instructions specifically for this purpose.
LLM_NON_CUSTOM_QUERY_WEIGHT = 0.7
# This is much lower weight because it is likely pretty similar to the LLM semantic query but just worse quality.
ORIGINAL_QUERY_WEIGHT = 0.5

# Hybrid Search Configuration
# This may in the future just use an entirely keyword search. Currently it is a hybrid search with a keyword first phase.
KEYWORD_QUERY_HYBRID_ALPHA = 0.2

# Reciprocal Rank Fusion
RRF_K_VALUE = 50

# Context Expansion
FULL_DOC_NUM_CHUNKS_AROUND = 5

# If a document is quite relevant and has many returned sections, likely it's enough to use the chunks around
# the highest scoring section to detect relevance. This allows more other docs to be evaluated in the step.
# This avoids documents with good titles or generally strong matches to flood out the rest of the search results.
# If there are multiple indepedent sections from the doc, this won't truncate it, only if they're connected.
MAX_CHUNKS_FOR_RELEVANCE = 3
