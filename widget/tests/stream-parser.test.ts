import { test } from "node:test";
import { strict as assert } from "node:assert";
import { ChatStreamParser } from "../src/services/stream-parser";
import type { Packet } from "../src/types/api-types";

const identity = { message_id: "root:0", part_id: "answer" };
const answer: Packet = {
  identity,
  obj: {
    type: "item_update",
    item: {
      kind: "text",
      text: "",
      purpose: "answer",
      status: "running",
      citations: [],
      documents: [],
    },
  },
};

test("streamed answer is replaced by accepted content, with final citations", () => {
  const parser = new ChatStreamParser();
  let message = parser.process(answer, null).message;
  message = parser.process(
    {
      identity,
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "Partial", citations: [] },
      },
    },
    message
  ).message;
  assert.equal(message?.content, "Partial");
  const result = parser.process(
    {
      identity,
      obj: {
        type: "item_update",
        item: {
          kind: "text",
          text: "Complete answer",
          purpose: "answer",
          status: "complete",
          documents: [],
          citations: [{ citation_number: 1, document_id: "doc" }],
        },
      },
    },
    message
  );
  assert.equal(result.message?.content, "Complete answer");
  assert.deepEqual(result.citations, [
    { citation_number: 1, document_id: "doc" },
  ]);
  assert.equal(
    parser.process({ obj: { type: "stop" } }, result.message).message
      ?.isStreaming,
    false
  );
});

test("child content and root reasoning do not append to the answer", () => {
  const parser = new ChatStreamParser();
  const message = parser.process(answer, null).message;
  const child = parser.process(
    {
      identity: { ...identity, parent_run_id: "root" },
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "child report", citations: [] },
      },
    },
    message
  );
  assert.equal(child.message?.content, "");
  const thinking = parser.process(
    {
      identity: { ...identity, part_id: "reasoning" },
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "thinking", citations: [] },
      },
    },
    message
  );
  assert.equal(thinking.message?.content, "");
});
