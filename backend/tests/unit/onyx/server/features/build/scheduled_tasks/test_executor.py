from onyx.server.features.build.scheduled_tasks.executor import _clip_summary
from onyx.server.features.build.scheduled_tasks.executor import SUMMARY_MAX_CHARS


def test_clip_summary_short_text_passthrough() -> None:
    assert _clip_summary("All done.") == "All done."


def test_clip_summary_exactly_max_passthrough() -> None:
    text = "x" * SUMMARY_MAX_CHARS
    assert _clip_summary(text) == text


def test_clip_summary_clips_at_word_boundary_with_ellipsis() -> None:
    text = ("word " * 40).strip()
    clipped = _clip_summary(text)
    words_kept = SUMMARY_MAX_CHARS // len("word ") - 1
    assert clipped == "word " * words_kept + "word…"
    assert len(clipped) <= SUMMARY_MAX_CHARS + 1


def test_clip_summary_no_space_falls_back_to_hard_cut() -> None:
    text = "x" * 200
    assert _clip_summary(text) == "x" * SUMMARY_MAX_CHARS + "…"


def test_clip_summary_early_space_does_not_discard_snippet() -> None:
    text = "Done: " + "a" * 200
    clipped = _clip_summary(text)
    assert clipped == text[:SUMMARY_MAX_CHARS] + "…"


def test_clip_summary_strips_trailing_space_before_ellipsis() -> None:
    text = "word " * 40
    clipped = _clip_summary(text)
    assert not clipped[:-1].endswith(" ")
    assert clipped.endswith("…")
