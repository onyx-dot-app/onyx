export const GENERIC_CHAT_ERROR_MESSAGE =
  "Something went wrong while generating a response. Please try again.";

const STACK_TRACE_MARKERS = [
  "Traceback (most recent call last)",
  "Exception Group Traceback",
  "During handling of the above exception",
];

const STACK_TRACE_FILE_LINE = /^\s*File "/gm;

function looksLikeStackTrace(text: string): boolean {
  if (STACK_TRACE_MARKERS.some((marker) => text.includes(marker))) {
    return true;
  }

  return (text.match(STACK_TRACE_FILE_LINE) || []).length >= 2;
}

/**
 * Ensure chat error text shown to users never includes backend stack traces.
 */
export function sanitizeChatErrorForDisplay(
  error: string | null | undefined
): string {
  if (!error?.trim()) {
    return GENERIC_CHAT_ERROR_MESSAGE;
  }

  const trimmed = error.trim();
  if (!looksLikeStackTrace(trimmed)) {
    return trimmed;
  }

  for (const marker of STACK_TRACE_MARKERS) {
    const markerIndex = trimmed.indexOf(marker);
    if (markerIndex > 0) {
      const beforeTrace = trimmed.slice(0, markerIndex).trim();
      if (beforeTrace.length > 0 && !looksLikeStackTrace(beforeTrace)) {
        return beforeTrace;
      }
    }
  }

  return GENERIC_CHAT_ERROR_MESSAGE;
}
