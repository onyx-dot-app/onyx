QUERY_REPORT_NAME_PREFIX = "query-history"


def construct_query_history_report_name(
    task_id: str,
) -> str:
    return f"{QUERY_REPORT_NAME_PREFIX}-{task_id}.csv"


def extract_task_id_from_query_history_report_name(name: str) -> str:
    return name.removeprefix(f"{QUERY_REPORT_NAME_PREFIX}-").removesuffix(".csv")
