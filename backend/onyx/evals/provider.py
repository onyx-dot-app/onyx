from onyx.evals.models import EvalProvider
from onyx.evals.providers.braintrust import BraintrustEvalProvider


def get_default_provider() -> EvalProvider:
    return BraintrustEvalProvider()
