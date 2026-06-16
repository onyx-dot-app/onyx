## Summary

Fixes #11932

When the LLM stream ends (token=None), `self.hold` could still contain characters from a partial stop-stream match that turned out to be a false alarm. Previously, only `self.curr_segment` was flushed in the end-of-stream handler, causing the held characters to be silently dropped and the LLM output to be truncated mid-word at the very end.

This is most likely to trigger when an answer ends shortly after a citation, which is common with well-cited RAG responses.

## Changes

```python
# Before (bug):
if token is None:
    if self.curr_segment:
        yield self.curr_segment
    return

# After (fix):
if token is None:
    remaining = self.hold + self.curr_segment
    if remaining:
        yield remaining
    self.hold = ""
    return
```

## Why this fix is safe

- `self.hold` only ever contains characters that partially matched the `stop_stream` pattern prefix. If the stream ends without completing the match, these characters are legitimate output that should be emitted as plain text.
- Held content is very unlikely to contain a complete citation (it's at most a few characters of a partial stop-pattern match), so emitting it as plain text is acceptable.
- `self.hold` is reset to empty string after flushing to maintain clean state.

## Testing

Added 4 new test cases in `TestHoldBufferFlushOnStreamEnd`:
1. `test_hold_flushed_on_stream_end_with_stop_stream` — verifies held characters are emitted
2. `test_hold_and_curr_segment_both_flushed` — verifies both buffers are combined and flushed
3. `test_no_truncation_with_citation_near_end` — end-to-end scenario matching the original bug report
4. `test_hold_cleared_after_flush` — verifies `self.hold` is reset

All existing tests continue to pass.
