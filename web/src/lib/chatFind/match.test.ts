import type { Message } from "@/app/app/types";
import type { Packet } from "@/app/app/services/streamingModels";
import {
  answerFindSegments,
  chatFindMatchAt,
  chatFindTexts,
  findChatMatches,
  findOccurrences,
  stepChatFindIndex,
} from "@/lib/chatFind/match";

function message(fields: Partial<Message> & Pick<Message, "nodeId">): Message {
  return {
    message: "",
    type: "user",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [],
    ...fields,
  };
}

function answerPackets(...deltas: string[]): Packet[] {
  return deltas.map((content, index) => ({
    placement: { turn_index: 0 },
    obj:
      index === 0
        ? { type: "message_start", id: "m", content, final_documents: null }
        : { type: "message_delta", content },
  }));
}

describe("findOccurrences", () => {
  it("ignores case and does not overlap", () => {
    expect(findOccurrences("Foo foo FOO", "foo")).toEqual([0, 4, 8]);
    expect(findOccurrences("aaaa", "aa")).toEqual([0, 2]);
  });

  it("finds a curly apostrophe from a straight one", () => {
    expect(findOccurrences("it’s here", "it's")).toEqual([0]);
  });

  it("finds nothing for an empty query", () => {
    expect(findOccurrences("text", "")).toEqual([]);
  });
});

describe("answerFindSegments", () => {
  it("keeps the text the answer shows, split at its blocks", () => {
    expect(
      answerFindSegments(
        "# Title\n\nSome **bold** `code` text[[1]](https://a.b).\n\n```py\nprint('x')\nprint('y')\n```"
      )
    ).toEqual([
      "Title",
      "Some bold code text",
      ".",
      "print('x')",
      "print('y')",
    ]);
  });

  it("keeps a details summary and drops a callout marker", () => {
    expect(
      answerFindSegments(
        "> [!NOTE]\n> Mind the note.\n\n<details><summary>More note</summary>\n\nHidden note text.\n\n</details>"
      )
    ).toEqual(["Mind the note.", "More note", "Hidden note text."]);
  });

  it("skips math", () => {
    expect(answerFindSegments("Area $$x^2$$ here")).toEqual(["Area ", " here"]);
  });
});

describe("findChatMatches", () => {
  const messages = [
    message({ nodeId: 1, message: "Where is the foo?" }),
    message({
      nodeId: 2,
      type: "assistant",
      parentNodeId: 1,
      packets: answerPackets("The foo is ", "next to **Foo** and `foo()`."),
    }),
    message({ nodeId: 3, message: "Thanks", parentNodeId: 2 }),
  ];

  it("counts the matches of each message in chat order", () => {
    const { entries, total } = findChatMatches(
      chatFindTexts(messages, null),
      "foo"
    );
    expect(total).toBe(4);
    expect(
      entries.map(({ nodeId, kind, start, count }) => ({
        nodeId,
        kind,
        start,
        count,
      }))
    ).toEqual([
      { nodeId: 1, kind: "user", start: 0, count: 1 },
      { nodeId: 2, kind: "answer", start: 1, count: 3 },
    ]);
  });

  it("maps an index to its message, row and occurrence", () => {
    const { entries } = findChatMatches(chatFindTexts(messages, null), "foo");
    expect(chatFindMatchAt(entries, 3)).toEqual({
      nodeId: 2,
      rowId: "message-2",
      kind: "answer",
      occurrence: 2,
    });
    expect(chatFindMatchAt(entries, 4)).toBeNull();
  });
});

describe("stepChatFindIndex", () => {
  it("wraps around both ends", () => {
    expect(stepChatFindIndex(2, 3, 1)).toBe(0);
    expect(stepChatFindIndex(0, 3, -1)).toBe(2);
    expect(stepChatFindIndex(0, 0, 1)).toBe(0);
  });
});
