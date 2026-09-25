import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { render } from "@testing-library/react-native";
import { Fragment } from "react";

import { makePacket } from "@/chat/__tests__/fixtures";

import { MessageTextRenderer } from "../MessageTextRenderer";
import { RenderType, type RendererOutput } from "../timelineContract";

// StreamingMarkdown pulls a native markdown module; capture its props instead of rendering. Capturing
// `isStreaming` lets tests pin the completion signal directly, not just via onComplete.
let mockMarkdownProps: { content: string; isStreaming: boolean } | null = null;
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: (props: { content: string; isStreaming: boolean }) => {
    mockMarkdownProps = props;
    return null;
  },
}));

const chatPackets = [
  makePacket({
    type: "message_start",
    id: "m",
    content: "Hello ",
    final_documents: null,
  }),
  makePacket({ type: "message_delta", content: "world" }),
];

function renderResults(results: RendererOutput) {
  return (
    <>
      {results.map((result, index) => (
        <Fragment key={index}>{result.content}</Fragment>
      ))}
    </>
  );
}

describe("MessageTextRenderer", () => {
  beforeEach(() => {
    mockMarkdownProps = null;
  });

  it("accumulates message_start + delta content and snaps historical messages to full", () => {
    render(
      <MessageTextRenderer
        packets={chatPackets}
        state={{ agent: null }}
        onComplete={() => {}}
        renderType={RenderType.FULL}
        animate={false}
        stopPacketSeen={true}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    // animate=false snaps the typewriter to full immediately.
    expect(mockMarkdownProps?.content).toBe("Hello world");
    expect(mockMarkdownProps?.isStreaming).toBe(false);
  });

  it("emits a single render-prop result with no icon or status", () => {
    let captured: RendererOutput | null = null;
    render(
      <MessageTextRenderer
        packets={chatPackets}
        state={{ agent: null }}
        onComplete={() => {}}
        renderType={RenderType.FULL}
        animate={false}
        stopPacketSeen={true}
      >
        {(results) => {
          captured = results;
          return <></>;
        }}
      </MessageTextRenderer>,
    );
    expect(captured).toHaveLength(1);
    expect(captured![0].icon).toBeNull();
    expect(captured![0].status).toBeNull();
  });

  it("treats a MESSAGE_END packet as complete even without a STOP (messageEndSeen branch)", () => {
    // stopPacketSeen=false → only the messageEndSeen half of isStreamFinished can drive completion.
    const endedPackets = [
      makePacket({
        type: "message_start",
        id: "m",
        content: "Hello ",
        final_documents: null,
      }),
      makePacket({ type: "message_delta", content: "world" }),
      makePacket({ type: "message_end" }),
    ];
    let calls = 0;
    render(
      <MessageTextRenderer
        packets={endedPackets}
        state={{ agent: null }}
        onComplete={() => {
          calls += 1;
        }}
        renderType={RenderType.FULL}
        animate={false}
        stopPacketSeen={false}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    expect(mockMarkdownProps?.content).toBe("Hello world");
    expect(mockMarkdownProps?.isStreaming).toBe(false);
    expect(calls).toBe(1);
  });

  it("fires onComplete exactly once even as onComplete's identity churns across re-renders", () => {
    let calls = 0;
    const props = {
      packets: chatPackets,
      state: { agent: null },
      renderType: RenderType.FULL,
      animate: false,
      stopPacketSeen: true,
    } as const;
    const { rerender } = render(
      <MessageTextRenderer
        {...props}
        onComplete={() => {
          calls += 1;
        }}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    // A fresh onComplete arrow each time changes the effect's dependency; the ref guard must still
    // suppress re-firing.
    rerender(
      <MessageTextRenderer
        {...props}
        onComplete={() => {
          calls += 1;
        }}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    rerender(
      <MessageTextRenderer
        {...props}
        onComplete={() => {
          calls += 1;
        }}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    expect(calls).toBe(1);
  });

  it("reveals content gradually and withholds onComplete while streaming (live path)", () => {
    // animate=true + no MESSAGE_END/STOP → the typewriter starts empty and reveals over rAF.
    const streaming = [
      makePacket({
        type: "message_start",
        id: "m",
        content: "",
        final_documents: null,
      }),
      makePacket({ type: "message_delta", content: "A".repeat(60) }),
    ];
    let calls = 0;
    render(
      <MessageTextRenderer
        packets={streaming}
        state={{ agent: null }}
        onComplete={() => {
          calls += 1;
        }}
        renderType={RenderType.FULL}
        animate={true}
        stopPacketSeen={false}
      >
        {renderResults}
      </MessageTextRenderer>,
    );
    // A snap-to-full regression (content={content}) would show all 60 chars at once; the live typewriter
    // shows far fewer, stays streaming, and withholds onComplete until completion.
    expect((mockMarkdownProps?.content ?? "").length).toBeLessThan(60);
    expect(mockMarkdownProps?.isStreaming).toBe(true);
    expect(calls).toBe(0);
  });
});
