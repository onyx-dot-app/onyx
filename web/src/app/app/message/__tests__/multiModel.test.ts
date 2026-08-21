import { Message } from "@/app/app/interfaces";
import {
  chooseImplicitPreferred,
  getMultiModelChildren,
  getUnresolvedMultiModelTurn,
} from "@/app/app/message/multiModel";
import { getLatestMessageChain } from "@/app/app/services/messageTree";

let nextNodeId = 1;

function buildMessage(overrides: Partial<Message>): Message {
  return {
    nodeId: nextNodeId++,
    message: "",
    type: "assistant",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [],
    ...overrides,
  };
}

// Builds a multi-model turn: one response per entry of `models`, in panel
// layout order (first model last).
function buildTurn(
  tree: Map<number, Message>,
  models: (string | { model: string; type: "error" })[],
  options: { parent?: Message; preferredModel?: string } = {}
): { userMessage: Message; responses: Message[] } {
  const userMessage = buildMessage({
    type: "user",
    parentNodeId: options.parent?.nodeId ?? null,
    messageId: nextNodeId * 100,
  });
  const responses = models.map((entry) => {
    const model = typeof entry === "string" ? entry : entry.model;
    return buildMessage({
      type: typeof entry === "string" ? "assistant" : "error",
      parentNodeId: userMessage.nodeId,
      messageId: nextNodeId * 100,
      overridden_model: model,
      modelDisplayName: model,
    });
  });
  userMessage.childrenNodeIds = responses.map((r) => r.nodeId);
  const preferred = responses.find(
    (r) => r.overridden_model === options.preferredModel
  );
  userMessage.preferredResponseId = preferred?.messageId ?? null;
  userMessage.latestChildNodeId =
    preferred?.nodeId ?? responses.at(-1)?.nodeId ?? null;
  if (options.parent) {
    options.parent.childrenNodeIds = [
      ...(options.parent.childrenNodeIds ?? []),
      userMessage.nodeId,
    ];
    options.parent.latestChildNodeId = userMessage.nodeId;
  }
  tree.set(userMessage.nodeId, userMessage);
  responses.forEach((r) => tree.set(r.nodeId, r));
  return { userMessage, responses };
}

// The production chain walk, so tests exercise the same traversal onSubmit
// feeds the helpers.
const chainOf = getLatestMessageChain;

beforeEach(() => {
  nextNodeId = 1;
});

describe("getMultiModelChildren", () => {
  it("returns model-tagged assistant and error children in order", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, [
      "gpt-5",
      { model: "claude-opus-5", type: "error" },
    ]);
    expect(getMultiModelChildren(userMessage, tree)).toEqual(responses);
  });

  it("ignores turns without two model-tagged children", () => {
    const tree = new Map<number, Message>();
    const userMessage = buildMessage({ type: "user" });
    const regenerated = [
      buildMessage({ type: "assistant", parentNodeId: userMessage.nodeId }),
      buildMessage({ type: "assistant", parentNodeId: userMessage.nodeId }),
    ];
    userMessage.childrenNodeIds = regenerated.map((r) => r.nodeId);
    tree.set(userMessage.nodeId, userMessage);
    regenerated.forEach((r) => tree.set(r.nodeId, r));
    expect(getMultiModelChildren(userMessage, tree)).toBeNull();
  });
});

describe("getUnresolvedMultiModelTurn", () => {
  it("finds the last turn when no preferred response is set", () => {
    const tree = new Map<number, Message>();
    const { userMessage, responses } = buildTurn(tree, [
      "gpt-5",
      "claude-opus-5",
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree);
    expect(turn?.userMessage).toBe(userMessage);
    expect(turn?.responses).toEqual(responses);
  });

  it("returns null once a preferred response exists", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, ["gpt-5", "claude-opus-5"], {
      preferredModel: "gpt-5",
    });
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });

  it("returns null for single-model turns", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, ["gpt-5"]);
    expect(getUnresolvedMultiModelTurn(chainOf(tree), tree)).toBeNull();
  });
});

describe("chooseImplicitPreferred", () => {
  it("keeps the model preferred in the previous turn", () => {
    const tree = new Map<number, Message>();
    const first = buildTurn(tree, ["gemini-3", "gpt-5"], {
      preferredModel: "gemini-3",
    });
    const second = buildTurn(tree, ["gemini-3", "gpt-5"], {
      parent: first.responses[0],
    });
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      second.responses[0]
    );
  });

  it("falls back to the first model (last child) without a prior preference", () => {
    const tree = new Map<number, Message>();
    const { responses } = buildTurn(tree, ["gemini-3", "gpt-5"]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      responses[1]
    );
  });

  it("falls back to the first model when the prior model did not answer this turn", () => {
    const tree = new Map<number, Message>();
    const first = buildTurn(tree, ["gemini-3", "gpt-5"], {
      preferredModel: "gemini-3",
    });
    const second = buildTurn(tree, ["claude-opus-5", "gpt-5"], {
      parent: first.responses[0],
    });
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      second.responses[1]
    );
  });

  it("never assumes an errored response", () => {
    const tree = new Map<number, Message>();
    const { responses } = buildTurn(tree, [
      "gemini-3",
      { model: "gpt-5", type: "error" },
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBe(
      responses[0]
    );
  });

  it("returns null when every response errored", () => {
    const tree = new Map<number, Message>();
    buildTurn(tree, [
      { model: "gemini-3", type: "error" },
      { model: "gpt-5", type: "error" },
    ]);
    const turn = getUnresolvedMultiModelTurn(chainOf(tree), tree)!;
    expect(chooseImplicitPreferred(chainOf(tree), tree, turn)).toBeNull();
  });
});
