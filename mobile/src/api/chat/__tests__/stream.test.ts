import { describe, expect, it, jest } from "@jest/globals";

import { isMessageIdInfo, isPacket, type StreamEvent } from "@/api/chat/stream";

// jest.mock is hoisted above imports. Mock expo/fetch (module-scope import), and stub state/session so the
// config→session→storage chain doesn't load the real MMKV native module under jest.
jest.mock("expo/fetch", () => ({ fetch: jest.fn() }));
jest.mock("@/state/session", () => ({ getStoredServerUrl: () => null }));

const wrappedPacket = {
  placement: { turn_index: 0 },
  obj: { type: "message_delta", content: "x" },
} as unknown as StreamEvent;
const rootIdInfo = {
  user_message_id: 1,
  reserved_assistant_message_id: 2,
} as unknown as StreamEvent;

describe("stream discriminators", () => {
  it("isPacket matches wrapped packets, not root control objects", () => {
    expect(isPacket(wrappedPacket)).toBe(true);
    expect(isPacket(rootIdInfo)).toBe(false);
  });

  it("isMessageIdInfo matches the root id-info object, not wrapped packets", () => {
    expect(isMessageIdInfo(rootIdInfo)).toBe(true);
    expect(isMessageIdInfo(wrappedPacket)).toBe(false);
  });
});
