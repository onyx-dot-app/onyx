import {
  GENERIC_CHAT_ERROR_MESSAGE,
  sanitizeChatErrorForDisplay,
} from "./sanitizeChatError";

describe("sanitizeChatErrorForDisplay", () => {
  it("returns a generic message for empty input", () => {
    expect(sanitizeChatErrorForDisplay("")).toBe(GENERIC_CHAT_ERROR_MESSAGE);
    expect(sanitizeChatErrorForDisplay("   ")).toBe(GENERIC_CHAT_ERROR_MESSAGE);
    expect(sanitizeChatErrorForDisplay(null)).toBe(GENERIC_CHAT_ERROR_MESSAGE);
  });

  it("preserves user-friendly error messages", () => {
    expect(sanitizeChatErrorForDisplay("Rate limit exceeded.")).toBe(
      "Rate limit exceeded."
    );
  });

  it("replaces pure stack traces with a generic message", () => {
    const stackTrace = `Traceback (most recent call last):
  File "/app/onyx/chat/process_message.py", line 100, in stream_chat
    raise RuntimeError("boom")
RuntimeError: boom`;

    expect(sanitizeChatErrorForDisplay(stackTrace)).toBe(
      GENERIC_CHAT_ERROR_MESSAGE
    );
  });

  it("keeps user-facing text before a traceback", () => {
    const mixed = `The model provider returned an invalid response.
Traceback (most recent call last):
  File "/app/onyx/chat/process_message.py", line 100, in stream_chat
    raise RuntimeError("boom")`;

    expect(sanitizeChatErrorForDisplay(mixed)).toBe(
      "The model provider returned an invalid response."
    );
  });

  it("replaces a headerless multi-frame traceback with a generic message", () => {
    const headerless = `  File "/app/onyx/chat/process_message.py", line 100, in stream_chat
  File "/app/onyx/lib/utils.py", line 50, in helper
RuntimeError: boom`;

    expect(sanitizeChatErrorForDisplay(headerless)).toBe(
      GENERIC_CHAT_ERROR_MESSAGE
    );
  });
});
