from onyx.connectors.models import ConnectorCheckpoint


class DiscordCheckpoint(ConnectorCheckpoint):
    # Cached one-shot result of channel discovery on the first cycle.
    # None == "haven't enumerated channels yet"; once populated, never mutated.
    channel_ids: list[str] | None

    # Subset of channel_ids that are ForumChannels. Populated alongside channel_ids
    # at cold start; never mutated after. Consulted on rollover to pre-set
    # current_channel_main_exhausted=True (forums have no main-channel history).
    # Default [] so checkpoints persisted before PR2 deserialize cleanly.
    forum_channel_ids: list[str] = []

    # channel_id -> oldest seen message snowflake (we walk newest -> oldest like Slack).
    # Presence == "started"; value == "resume here via channel.history(before=...)".
    channel_completion_map: dict[str, str]

    # The channel currently being drained.
    current_channel_id: str | None

    # Invariant: current_channel_main_exhausted=False implies current_channel_thread_ids is None.
    # True once main-channel history for current_channel_id has returned a sub-full
    # page (i.e. main is exhausted). Differentiates phase 2 (fetch main page) from
    # phase 3 (enumerate threads) since both otherwise see current_channel_thread_ids=None.
    # Reset to False on channel rollover (phase 5).
    current_channel_main_exhausted: bool = False

    # Tri-state thread queue for current_channel_id:
    #   None       - haven't enumerated threads yet, do it next cycle
    #   []         - no threads (or skipped); ready to roll over to next channel
    #   non-empty  - drain in order, advance current_thread_id off the front
    # PR2 (forum channels) reuses this field unchanged.
    current_channel_thread_ids: list[str] | None

    # Cursor for paginating archived-thread enumeration across cycles. One archived
    # page (up to 100 threads) is fetched per cycle so that channels with thousands
    # of archived threads don't exceed the docfetching heartbeat budget.
    #   None == archived enumeration done (or never started; differentiated by
    #           current_channel_thread_ids).
    #   ""   == sentinel "first page, no `before=` cursor yet".
    #   "<snowflake>" == oldest archived-thread id seen so far; pass as `before=`.
    # Optional with default None so checkpoints persisted before this field was
    # added deserialize correctly: they enter phase 3 cold and go through the
    # paginated path from the start.
    archived_thread_cursor: str | None = None

    # thread_id -> oldest seen message snowflake. Same semantics as channel_completion_map.
    thread_completion_map: dict[str, str]

    # The thread currently being drained inside current_channel_id.
    # None == "no thread phase active" (main-channel phase or fully drained).
    current_thread_id: str | None
