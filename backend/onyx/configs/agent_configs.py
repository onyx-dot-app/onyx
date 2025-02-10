import os

INITIAL_SEARCH_DECOMPOSITION_ENABLED = True
ALLOW_REFINEMENT = True

AGENT_DEFAULT_RETRIEVAL_HITS = 15
AGENT_DEFAULT_RERANKING_HITS = 10
AGENT_DEFAULT_SUB_QUESTION_MAX_CONTEXT_HITS = 8
AGENT_DEFAULT_NUM_DOCS_FOR_INITIAL_DECOMPOSITION = 3
AGENT_DEFAULT_NUM_DOCS_FOR_REFINED_DECOMPOSITION = 5
AGENT_DEFAULT_EXPLORATORY_SEARCH_RESULTS = 5
AGENT_DEFAULT_MIN_ORIG_QUESTION_DOCS = 3
AGENT_DEFAULT_MAX_ANSWER_CONTEXT_DOCS = 10
AGENT_DEFAULT_MAX_STATIC_HISTORY_WORD_LENGTH = 2000

AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_GENERAL_GENERATION = 30  # in seconds

AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_HISTORY_SUMMARY_GENERATION = 10  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_ENTITY_TERM_EXTRACTION = 25  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_QUERY_REWRITING_GENERATION = 4  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_DOCUMENT_VERIFICATION = 3  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBQUESTION_GENERATION = 8  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_GENERATION = 12  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_CHECK = 8  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_INITIAL_ANSWER_GENERATION = 25  # in seconds

AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_REFINED_SUBQUESTION_GENERATION = 6  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_REFINED_ANSWER_GENERATION = 25  # in seconds
AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_COMPARE_ANSWERS = 8  # in seconds

#####
# Agent Configs
#####


AGENT_RETRIEVAL_STATS = (
    not os.environ.get("AGENT_RETRIEVAL_STATS") == "False"
) or True  # default True


AGENT_MAX_QUERY_RETRIEVAL_RESULTS = int(
    os.environ.get("AGENT_MAX_QUERY_RETRIEVAL_RESULTS") or AGENT_DEFAULT_RETRIEVAL_HITS
)  # 15

AGENT_MAX_QUERY_RETRIEVAL_RESULTS = int(
    os.environ.get("AGENT_MAX_QUERY_RETRIEVAL_RESULTS") or AGENT_DEFAULT_RETRIEVAL_HITS
)  # 15

# Reranking agent configs
# Reranking stats - no influence on flow outside of stats collection
AGENT_RERANKING_STATS = (
    not os.environ.get("AGENT_RERANKING_STATS") == "True"
) or False  # default False

AGENT_MAX_QUERY_RETRIEVAL_RESULTS = int(
    os.environ.get("AGENT_MAX_QUERY_RETRIEVAL_RESULTS") or AGENT_DEFAULT_RETRIEVAL_HITS
)  # 15

AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS = int(
    os.environ.get("AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS")
    or AGENT_DEFAULT_RERANKING_HITS
)  # 10

AGENT_NUM_DOCS_FOR_DECOMPOSITION = int(
    os.environ.get("AGENT_NUM_DOCS_FOR_DECOMPOSITION")
    or AGENT_DEFAULT_NUM_DOCS_FOR_INITIAL_DECOMPOSITION
)  # 3

AGENT_NUM_DOCS_FOR_REFINED_DECOMPOSITION = int(
    os.environ.get("AGENT_NUM_DOCS_FOR_REFINED_DECOMPOSITION")
    or AGENT_DEFAULT_NUM_DOCS_FOR_REFINED_DECOMPOSITION
)  # 5

AGENT_EXPLORATORY_SEARCH_RESULTS = int(
    os.environ.get("AGENT_EXPLORATORY_SEARCH_RESULTS")
    or AGENT_DEFAULT_EXPLORATORY_SEARCH_RESULTS
)  # 5

AGENT_MIN_ORIG_QUESTION_DOCS = int(
    os.environ.get("AGENT_MIN_ORIG_QUESTION_DOCS")
    or AGENT_DEFAULT_MIN_ORIG_QUESTION_DOCS
)  # 3

AGENT_MAX_ANSWER_CONTEXT_DOCS = int(
    os.environ.get("AGENT_MAX_ANSWER_CONTEXT_DOCS")
    or AGENT_DEFAULT_SUB_QUESTION_MAX_CONTEXT_HITS
)  # 8


AGENT_MAX_STATIC_HISTORY_WORD_LENGTH = int(
    os.environ.get("AGENT_MAX_STATIC_HISTORY_WORD_LENGTH")
    or AGENT_DEFAULT_MAX_STATIC_HISTORY_WORD_LENGTH
)  # 2000


AGENT_TIMEOUT_OVERRIDE_LLM_ENTITY_TERM_EXTRACTION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_ENTITY_TERM_EXTRACTION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_ENTITY_TERM_EXTRACTION
)  # 25


AGENT_TIMEOUT_OVERRIDE_LLM_DOCUMENT_VERIFICATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_DOCUMENT_VERIFICATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_DOCUMENT_VERIFICATION
)  # 3

AGENT_TIMEOUT_OVERRIDE_LLM_GENERAL_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_GENERAL_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_GENERAL_GENERATION
)  # 30


AGENT_TIMEOUT_OVERRIDE_LLM_SUBQUESTION_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_SUBQUESTION_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBQUESTION_GENERATION
)  # 8


AGENT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_GENERATION
)  # 12


AGENT_TIMEOUT_OVERRIDE_LLM_INITIAL_ANSWER_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_INITIAL_ANSWER_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_INITIAL_ANSWER_GENERATION
)  # 25


AGENT_TIMEOUT_OVERRIDE_LLM_REFINED_ANSWER_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_REFINED_ANSWER_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_REFINED_ANSWER_GENERATION
)  # 25


AGENT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_CHECK = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_CHECK")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_SUBANSWER_CHECK
)  # 8


AGENT_TIMEOUT_OVERRIDE_LLM_REFINED_SUBQUESTION_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_REFINED_SUBQUESTION_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_REFINED_SUBQUESTION_GENERATION
)  # 6


AGENT_TIMEOUT_OVERRIDE_LLM_QUERY_REWRITING_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_QUERY_REWRITING_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_QUERY_REWRITING_GENERATION
)  # 1


AGENT_TIMEOUT_OVERRIDE_LLM_HISTORY_SUMMARY_GENERATION = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_HISTORY_SUMMARY_GENERATION")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_HISTORY_SUMMARY_GENERATION
)  # 4


AGENT_TIMEOUT_OVERRIDE_LLM_COMPARE_ANSWERS = int(
    os.environ.get("AGENT_TIMEOUT_OVERRIDE_LLM_COMPARE_ANSWERS")
    or AGENT_DEFAULT_TIMEOUT_OVERRIDE_LLM_COMPARE_ANSWERS
)  # 8


GRAPH_VERSION_NAME: str = "a"
