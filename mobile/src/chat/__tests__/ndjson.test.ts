import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";

import { createNdjsonBuffer } from "@/chat/ndjson";
import {
  ChatHeartbeat,
  MessageDelta,
  MessageResponseIDInfo,
  Packet,
} from "@/chat/streamingModels";

// silence + capture recovery-path logs
let errorSpy: ReturnType<typeof jest.spyOn>;
beforeEach(() => {
  errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  errorSpy.mockRestore();
});

const wrapped = (content: string): Packet => ({
  placement: { turn_index: 0 },
  obj: { type: "message_delta", content } as MessageDelta,
});

describe("createNdjsonBuffer", () => {
  it("parses a single complete line", () => {
    const buf = createNdjsonBuffer<Packet>();
    const out = buf.pushChunk(JSON.stringify(wrapped("hi")) + "\n");
    expect(out).toHaveLength(1);
    expect((out[0]!.obj as MessageDelta).content).toBe("hi");
  });

  it("parses multiple complete lines in one chunk", () => {
    const buf = createNdjsonBuffer<Packet>();
    const text =
      JSON.stringify(wrapped("a")) + "\n" + JSON.stringify(wrapped("b")) + "\n";
    const out = buf.pushChunk(text);
    expect(out.map((p) => (p.obj as MessageDelta).content)).toEqual(["a", "b"]);
  });

  it("carries a partial line across chunks until its newline arrives", () => {
    const buf = createNdjsonBuffer<Packet>();
    const line = JSON.stringify(wrapped("split"));
    const mid = Math.floor(line.length / 2);

    expect(buf.pushChunk(line.slice(0, mid))).toEqual([]);
    const out = buf.pushChunk(line.slice(mid) + "\n");
    expect(out).toHaveLength(1);
    expect((out[0]!.obj as MessageDelta).content).toBe("split");
  });

  it("splits a chunk that contains a line boundary mid-way", () => {
    const buf = createNdjsonBuffer<Packet>();
    const first = JSON.stringify(wrapped("one"));
    const second = JSON.stringify(wrapped("two"));

    const out1 = buf.pushChunk(first + "\n" + second.slice(0, 4));
    expect(out1).toHaveLength(1);
    expect((out1[0]!.obj as MessageDelta).content).toBe("one");

    const out2 = buf.pushChunk(second.slice(4) + "\n");
    expect((out2[0]!.obj as MessageDelta).content).toBe("two");
  });

  it("skips blank lines", () => {
    const buf = createNdjsonBuffer<Packet>();
    const out = buf.pushChunk(
      "\n\n" + JSON.stringify(wrapped("x")) + "\n\n   \n",
    );
    expect(out).toHaveLength(1);
  });

  it("is heartbeat-agnostic — returns heartbeats like any other packet", () => {
    const buf = createNdjsonBuffer<Packet>();
    const heartbeat: Packet = {
      placement: { turn_index: 0 },
      obj: { type: "chat_heartbeat" } as ChatHeartbeat,
    };
    const out = buf.pushChunk(JSON.stringify(heartbeat) + "\n");
    expect((out[0]!.obj as ChatHeartbeat).type).toBe("chat_heartbeat");
  });

  it("returns both wrapped packets and root control objects", () => {
    const buf = createNdjsonBuffer<Packet | MessageResponseIDInfo>();
    // Real wire shape: the message-id-info root carries no `type` field.
    const root: MessageResponseIDInfo = {
      user_message_id: 5,
      reserved_assistant_message_id: 6,
    };
    const text =
      JSON.stringify(root) + "\n" + JSON.stringify(wrapped("after")) + "\n";
    const out = buf.pushChunk(text);
    expect(out).toHaveLength(2);
    // discriminate root vs wrapped by field presence, not by `.type`
    expect("obj" in out[0]!).toBe(false);
    expect((out[0] as MessageResponseIDInfo).user_message_id).toBe(5);
    expect("obj" in out[1]!).toBe(true);
  });

  describe("brace-recovery fallback", () => {
    it("salvages flat JSON objects from a malformed line and logs", () => {
      const buf = createNdjsonBuffer<{ a?: number; b?: number }>();
      // two flat objects glued together = invalid as one line
      const out = buf.pushChunk(`{"a":1}garbage{"b":2}\n`);
      expect(out).toEqual([{ a: 1 }, { b: 2 }]);
      expect(errorSpy).toHaveBeenCalled();
    });

    it("cannot recover a malformed line whose objects are nested", () => {
      const buf = createNdjsonBuffer<unknown>();
      // nested braces defeat the flat recovery regex
      const out = buf.pushChunk(`{"placement":{"turn_index":0` + "\n");
      expect(out).toEqual([]);
      expect(errorSpy).toHaveBeenCalled();
    });
  });

  describe("flush", () => {
    it("parses a trailing line with no terminating newline", () => {
      const buf = createNdjsonBuffer<Packet>();
      expect(buf.pushChunk(JSON.stringify(wrapped("tail")))).toEqual([]);
      const out = buf.flush();
      expect(out).toHaveLength(1);
      expect((out[0]!.obj as MessageDelta).content).toBe("tail");
    });

    it("drops a malformed trailing buffer (no brace recovery) and logs", () => {
      const buf = createNdjsonBuffer<unknown>();
      buf.pushChunk(`{"a":1}x`);
      expect(buf.flush()).toEqual([]);
      expect(errorSpy).toHaveBeenCalled();
    });

    it("returns [] when nothing is buffered", () => {
      const buf = createNdjsonBuffer<unknown>();
      expect(buf.flush()).toEqual([]);
    });

    it("does not re-emit already-flushed content on a second flush", () => {
      const buf = createNdjsonBuffer<Packet>();
      buf.pushChunk(JSON.stringify(wrapped("once")));
      expect(buf.flush()).toHaveLength(1);
      expect(buf.flush()).toEqual([]);
    });
  });
});
