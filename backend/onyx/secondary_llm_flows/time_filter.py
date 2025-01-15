import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from dateutil.parser import parse

from onyx.llm.interfaces import LLM
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_to_string
from onyx.prompts.filter_extration import TIME_FILTER_PROMPT
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.utils.logger import setup_logger

logger = setup_logger()


def best_match_time(time_str: str) -> datetime | None:
    preferred_formats = ["%m/%d/%Y", "%m-%d-%Y"]

    for fmt in preferred_formats:
        try:
            # As we don't know if the user is interacting with the API server from
            # the same timezone as the API server, just assume the queries are UTC time
            # the few hours offset (if any) shouldn't make any significant difference
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # If the above formats don't match, try using dateutil's parser
    try:
        dt = parse(time_str)
        return (
            dt.astimezone(timezone.utc)
            if dt.tzinfo
            else dt.replace(tzinfo=timezone.utc)
        )
    except ValueError:
        return None


def extract_time_filter(query: str, llm: LLM) -> tuple[datetime | None, bool]:
    """Returns a datetime if a hard time filter should be applied for the given query
    Additionally returns a bool, True if more recently updated Documents should be
    heavily favored"""

    def _get_time_filter_messages(query: str) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": TIME_FILTER_PROMPT.format(
                    current_day_time_str=get_current_llm_day_time()
                ),
            },
            {
                "role": "user",
                "content": "What documents in Confluence were written in the last two quarters",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "filter_type": "hard cutoff",
                        "filter_value": "quarter",
                        "value_multiple": 2,
                    }
                ),
            },
            {"role": "user", "content": "What's the latest on project Corgies?"},
            {
                "role": "assistant",
                "content": json.dumps({"filter_type": "favor recent"}),
            },
            {
                "role": "user",
                "content": "Which customer asked about security features in February of 2022?",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {"filter_type": "hard cutoff", "date": "02/01/2022"}
                ),
            },
            {"role": "user", "content": query},
        ]
        return messages

    def _extract_time_filter_from_llm_out(
        model_out: str,
    ) -> tuple[datetime | None, bool]:
        """Returns a datetime for a hard cutoff and a bool for if the"""
        try:
            model_json = json.loads(model_out, strict=False)
        except json.JSONDecodeError:
            return None, False

        # If filter type is not present, just assume something has gone wrong
        # Potentially model has identified a date and just returned that but
        # better to be conservative and not identify the wrong filter.
        if "filter_type" not in model_json:
            return None, False

        if "hard" in model_json["filter_type"] or "recent" in model_json["filter_type"]:
            favor_recent = "recent" in model_json["filter_type"]

            if "date" in model_json:
                extracted_time = best_match_time(model_json["date"])
                if extracted_time is not None:
                    # LLM struggles to understand the concept of not sensitive within a time range
                    # So if a time is extracted, just go with that alone
                    return extracted_time, False

            time_diff = None
            multiplier = 1.0

            if "value_multiple" in model_json:
                try:
                    multiplier = float(model_json["value_multiple"])
                except ValueError:
                    pass

            if "filter_value" in model_json:
                filter_value = model_json["filter_value"]
                if "day" in filter_value:
                    time_diff = timedelta(days=multiplier)
                elif "week" in filter_value:
                    time_diff = timedelta(weeks=multiplier)
                elif "month" in filter_value:
                    # Have to just use the average here, too complicated to calculate exact day
                    # based on current day etc.
                    time_diff = timedelta(days=multiplier * 30.437)
                elif "quarter" in filter_value:
                    time_diff = timedelta(days=multiplier * 91.25)
                elif "year" in filter_value:
                    time_diff = timedelta(days=multiplier * 365)

            if time_diff is not None:
                current = datetime.now(timezone.utc)
                # LLM struggles to understand the concept of not sensitive within a time range
                # So if a time is extracted, just go with that alone
                return current - time_diff, False

            # If we failed to extract a hard filter, just pass back the value of favor recent
            return None, favor_recent

        return None, False

    messages = _get_time_filter_messages(query)
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(llm.invoke(filled_llm_prompt))
    logger.debug(model_output)

    return _extract_time_filter_from_llm_out(model_output)


if __name__ == "__main__":
    # Just for testing purposes, too tedious to unit test as it relies on an LLM
    from onyx.llm.factory import get_default_llms, get_main_llm_from_tuple

    while True:
        user_input = input("Query to Extract Time: ")
        cutoff, recency_bias = extract_time_filter(
            user_input, get_main_llm_from_tuple(get_default_llms())
        )
        print(f"Time Cutoff: {cutoff}")
        print(f"Favor Recent: {recency_bias}")
