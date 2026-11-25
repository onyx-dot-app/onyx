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

  it("skips a link that shows as an image", () => {
    expect(
      answerFindSegments("See [plot.png](/api/chat/file/abc) and [notes](/x).")
    ).toEqual(["See ", " and notes."]);
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

  it("counts the matches of each text in chat order", () => {
    const { entries, total } = findChatMatches(
      chatFindTexts(messages, null),
      "foo"
    );
    expect(total).toBe(4);
    expect(
      entries.map(({ scopeKey, start, count }) => ({ scopeKey, start, count }))
    ).toEqual([
      { scopeKey: "user:1", start: 0, count: 1 },
      { scopeKey: "answer:2", start: 1, count: 3 },
    ]);
  });

  it("maps an index to its scope, row and occurrence", () => {
    const { entries } = findChatMatches(chatFindTexts(messages, null), "foo");
    expect(chatFindMatchAt(entries, 3)).toEqual({
      scopeKey: "answer:2",
      rowId: "message-2",
      occurrence: 2,
    });
    expect(chatFindMatchAt(entries, 4)).toBeNull();
  });

  it("searches messages sent during a reply, in turn order", () => {
    const reply = message({
      nodeId: 2,
      type: "assistant",
      parentNodeId: 1,
      packets: [
        ...answerPackets("First foo."),
        {
          placement: { turn_index: 1 },
          obj: {
            type: "user_message",
            id: "u1",
            message: "foo again",
            mentions: [],
          },
        },
        {
          placement: { turn_index: 2 },
          obj: {
            type: "message_start",
            id: "m2",
            content: "Last foo.",
            final_documents: null,
          },
        },
      ],
    });
    const { entries } = findChatMatches(chatFindTexts([reply], null), "foo");
    expect(
      entries.map(({ scopeKey, occurrenceStart }) => ({
        scopeKey,
        occurrenceStart,
      }))
    ).toEqual([
      { scopeKey: "answer:2", occurrenceStart: 0 },
      { scopeKey: "inline:2:u1", occurrenceStart: 0 },
      { scopeKey: "answer:2", occurrenceStart: 1 },
    ]);
  });

  it("skips answer text of a nested call", () => {
    const reply = message({
      nodeId: 2,
      type: "assistant",
      parentNodeId: 1,
      packets: [
        ...answerPackets("Main foo."),
        {
          placement: { turn_index: 0, sub_turn_index: 0 },
          obj: {
            type: "message_start",
            id: "child",
            content: "Child foo.",
            final_documents: null,
          },
        },
      ],
    });
    expect(findChatMatches(chatFindTexts([reply], null), "foo").total).toBe(1);
  });

  it("splits a user message at its mention chips", () => {
    const question = message({
      nodeId: 1,
      message: "use @lint now",
      mentions: [{ type: "skill", name: "lint" }],
    });
    const { total } = findChatMatches(chatFindTexts([question], null), "e @l");
    expect(total).toBe(0);
    expect(
      findChatMatches(chatFindTexts([question], null), "@lint").total
    ).toBe(1);
  });

  it("searches every answer of a multi-model turn in the question's row", () => {
    const question = message({
      nodeId: 1,
      message: "Compare",
      childrenNodeIds: [2, 3],
    });
    const first = message({
      nodeId: 2,
      type: "assistant",
      parentNodeId: 1,
      modelDisplayName: "A",
      packets: answerPackets("alpha foo"),
    });
    const second = message({
      nodeId: 3,
      type: "assistant",
      parentNodeId: 1,
      modelDisplayName: "B",
      packets: answerPackets("beta foo"),
    });
    const tree = new Map([
      [1, question],
      [2, first],
      [3, second],
    ]);
    const { entries } = findChatMatches(
      chatFindTexts([question, first], tree),
      "foo"
    );
    expect(entries.map(({ scopeKey, rowId }) => ({ scopeKey, rowId }))).toEqual(
      [
        { scopeKey: "answer:2", rowId: "message-1" },
        { scopeKey: "answer:3", rowId: "message-1" },
      ]
    );
  });
});

describe("stepChatFindIndex", () => {
  it("wraps around both ends", () => {
    expect(stepChatFindIndex(2, 3, 1)).toBe(0);
    expect(stepChatFindIndex(0, 3, -1)).toBe(2);
    expect(stepChatFindIndex(0, 0, 1)).toBe(0);
  });
});
