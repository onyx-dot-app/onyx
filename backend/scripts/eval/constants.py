OPENAI_API_KEY = "REPLACE_WITH_OPENAI_API_KEY"

# Metric thresholds (currently using default thresholds from deepeval)
HALLUCINATION_THRESHOLD = 0.3
ANSWER_RELEVANCY_THRESHOLD = 0.7
FAITHFULNESS_THRESHOLD = 0.5
CORRECTNESS_THRESHOLD = 0.5
CONTEXTUAL_RELEVANCY_THRESHOLD = 0.7
CONTEXTUAL_PRECISION_THRESHOLD = 0.7
CONTEXTUAL_RECALL_THRESHOLD = 0.7
EVAL_MODEL = "gpt-4.1-mini"
EVAL_INPUT_FILE = "REPLACE_WITH_PATH_TO_EVAL_INPUT_FILE"

# GEval criteria
CORRECTNESS_CRITERIA = "Determine if the 'actual output' is correct based on the 'expected output' and the 'input'. Outputs should be contextualized in the frame of the query 'input'. They may be phrased differently, but can still adequately address the query."
