from onyx.db.enums import IncognitoRecordMode
from shared_configs.contextvars import get_current_incognito_record_mode


def suppresses_external_traces() -> bool:
    """External tracing processors must check this at trace start and drop the
    whole trace, spans included, when True."""
    mode = IncognitoRecordMode.from_context_value(get_current_incognito_record_mode())
    return mode is not None and not mode.emits_external_traces
