from onyx.db.chat_run import next_event_seq


def test_next_event_seq_starts_at_zero() -> None:
    assert next_event_seq([]) == 0


def test_next_event_seq_increments_after_existing_events() -> None:
    class Event:
        def __init__(self, seq: int) -> None:
            self.seq = seq

    assert next_event_seq([Event(0), Event(1), Event(2)]) == 3
