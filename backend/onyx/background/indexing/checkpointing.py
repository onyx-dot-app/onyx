"""Experimental functionality related to splitting up indexing
into a series of checkpoints to better handle intermittent failures
/ jobs being killed by cloud providers."""
import datetime

from onyx.configs.app_configs import EXPERIMENTAL_CHECKPOINTING_ENABLED
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc


def _2010_dt() -> datetime.datetime:
    return datetime.datetime(year=2010, month=1, day=1, tzinfo=datetime.timezone.utc)


def _2020_dt() -> datetime.datetime:
    return datetime.datetime(year=2020, month=1, day=1, tzinfo=datetime.timezone.utc)


def _default_end_time(
    last_successful_run: datetime.datetime | None,
) -> datetime.datetime:
    """If year is before 2010, go to the beginning of 2010.
    If year is 2010-2020, go in 5 year increments.
    If year > 2020, then go in 180 day increments.

    For connectors that don't support a `filter_by` and instead rely on `sort_by`
    for polling, then this will cause a massive duplication of fetches. For these
    connectors, you may want to override this function to return a more reasonable
    plan (e.g. extending the 2020+ windows to 6 months, 1 year, or higher)."""
    last_successful_run = (
        datetime_to_utc(last_successful_run) if last_successful_run else None
    )
    if last_successful_run is None or last_successful_run < _2010_dt():
        return _2010_dt()

    if last_successful_run < _2020_dt():
        return min(last_successful_run + datetime.timedelta(days=365 * 5), _2020_dt())

    return last_successful_run + datetime.timedelta(days=180)


def find_end_time_for_indexing_attempt(
    last_successful_run: datetime.datetime | None,
    # source_type can be used to override the default for certain connectors, currently unused
    source_type: DocumentSource,
) -> datetime.datetime | None:
    """Is the current time unless the connector is run over a large period, in which case it is
    split up into large time segments that become smaller as it approaches the present
    """
    # NOTE: source_type can be used to override the default for certain connectors
    end_of_window = _default_end_time(last_successful_run)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if end_of_window < now:
        return end_of_window

    # None signals that we should index up to current time
    return None


def get_time_windows_for_index_attempt(
    last_successful_run: datetime.datetime, source_type: DocumentSource
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    if not EXPERIMENTAL_CHECKPOINTING_ENABLED:
        return [(last_successful_run, datetime.datetime.now(tz=datetime.timezone.utc))]

    time_windows: list[tuple[datetime.datetime, datetime.datetime]] = []
    start_of_window: datetime.datetime | None = last_successful_run
    while start_of_window:
        end_of_window = find_end_time_for_indexing_attempt(
            last_successful_run=start_of_window, source_type=source_type
        )
        time_windows.append(
            (
                start_of_window,
                end_of_window or datetime.datetime.now(tz=datetime.timezone.utc),
            )
        )
        start_of_window = end_of_window

    return time_windows
