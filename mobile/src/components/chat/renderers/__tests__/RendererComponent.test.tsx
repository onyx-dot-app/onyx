import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { render } from "@testing-library/react-native";
import { Fragment } from "react";

import { makePacket } from "@/chat/__tests__/fixtures";

import { RendererComponent } from "../RendererComponent";
import { type RendererOutput } from "../timelineContract";

let mockMarkdownContent: string | null = null;
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: (props: { content: string }) => {
    mockMarkdownContent = props.content;
    return null;
  },
}));

function renderResults(results: RendererOutput) {
  return (
    <>
      {results.map((result, index) => (
        <Fragment key={index}>{result.content}</Fragment>
      ))}
    </>
  );
}

describe("RendererComponent", () => {
  beforeEach(() => {
    mockMarkdownContent = null;
  });

  it("dispatches chat packets to the final-answer renderer", () => {
    render(
      <RendererComponent
        packets={[
          makePacket({
            type: "message_start",
            id: "m",
            content: "Hello ",
            final_documents: null,
          }),
          makePacket({ type: "message_delta", content: "world" }),
        ]}
        chatState={{ agent: null }}
        onComplete={() => {}}
        animate={false}
        stopPacketSeen={true}
      >
        {renderResults}
      </RendererComponent>,
    );
    expect(mockMarkdownContent).toBe("Hello world");
  });

  it("hands children an empty result when no renderer matches", () => {
    let captured: RendererOutput | null = null;
    render(
      <RendererComponent
        packets={[]}
        chatState={{ agent: null }}
        onComplete={() => {}}
        animate={false}
        stopPacketSeen={false}
      >
        {(results) => {
          captured = results;
          return <></>;
        }}
      </RendererComponent>,
    );
    expect(captured).toHaveLength(1);
    expect(captured![0].icon).toBeNull();
    expect(captured![0].status).toBeNull();
    // No renderer ran, so the markdown stub was never invoked.
    expect(mockMarkdownContent).toBeNull();
  });
});
