import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";

import { Message, MessageType } from "@/chat/interfaces";
import {
  buildEmptyMessage,
  buildImmediateMessages,
  getLastSuccessfulMessageId,
  getLatestMessageChain,
  getMessageByMessageId,
  setMessageAsLatest,
  SYSTEM_NODE_ID,
  upsertMessages,
  type MessageTreeState,
} from "@/chat/messageTree";

function node(
  nodeId: number,
  type: MessageType,
  parentNodeId: number | null,
  extra: Partial<Message> = {},
): Message {
  return {
    nodeId,
    type,
    parentNodeId,
    message: "",
    files: [],
    packets: [],
    ...extra,
  };
}

let warnSpy: ReturnType<typeof jest.spyOn>;
let errorSpy: ReturnType<typeof jest.spyOn>;
beforeEach(() => {
  warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
  errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  warnSpy.mockRestore();
  errorSpy.mockRestore();
});

describe("buildEmptyMessage", () => {
  it("creates a placeholder with a negative temp nodeId and empty packets", () => {
    const m = buildEmptyMessage({ messageType: "user", parentNodeId: -3 });
    expect(m.nodeId).toBeLessThan(0);
    expect(m.type).toBe("user");
    expect(m.parentNodeId).toBe(-3);
    expect(m.packets).toEqual([]);
    expect(m.files).toEqual([]);
  });
});

describe("buildImmediateMessages", () => {
  it("links an assistant placeholder under a new user node", () => {
    const { initialUserNode, initialAgentNode } = buildImmediateMessages(
      SYSTEM_NODE_ID,
      "hello",
      [],
    );
    expect(initialUserNode.type).toBe("user");
    expect(initialUserNode.message).toBe("hello");
    expect(initialAgentNode.type).toBe("assistant");
    expect(initialAgentNode.parentNodeId).toBe(initialUserNode.nodeId);
    expect(initialUserNode.childrenNodeIds).toEqual([initialAgentNode.nodeId]);
    expect(initialUserNode.latestChildNodeId).toBe(initialAgentNode.nodeId);
    expect(initialUserNode.nodeId).not.toBe(initialAgentNode.nodeId);
  });
});

describe("upsertMessages", () => {
  it("injects a synthetic system root and reparents a root-less first message", () => {
    const tree = upsertMessages(new Map(), [node(100, "user", null)]);

    const system = tree.get(SYSTEM_NODE_ID);
    expect(system).toBeDefined();
    expect(system!.type).toBe("system");
    expect(system!.childrenNodeIds).toEqual([100]);
    expect(system!.latestChildNodeId).toBe(100);
    expect(tree.get(100)!.parentNodeId).toBe(SYSTEM_NODE_ID);
  });

  it("does not mutate the input map (immutable upsert)", () => {
    const original: MessageTreeState = new Map();
    upsertMessages(original, [node(100, "user", null)]);
    expect(original.size).toBe(0);
  });

  it("links a child under its parent", () => {
    let tree = upsertMessages(new Map(), [node(100, "user", null)]);
    tree = upsertMessages(tree, [node(101, "assistant", 100)]);
    expect(tree.get(100)!.childrenNodeIds).toEqual([101]);
    expect(tree.get(100)!.latestChildNodeId).toBe(101);
  });

  it("makeLatestChildMessage=true forces an existing child back to active", () => {
    let tree = upsertMessages(new Map(), [node(100, "user", null)]);
    tree = upsertMessages(tree, [node(101, "assistant", 100)]);
    tree = upsertMessages(tree, [node(102, "assistant", 100)]); // 102 now latest
    tree = setMessageAsLatest(tree, 101); // switch away to 101

    // re-upserting the existing 102 with makeLatest forces it active again
    tree = upsertMessages(tree, [node(102, "assistant", 100)], true);
    expect(tree.get(100)!.latestChildNodeId).toBe(102);
    expect(getLatestMessageChain(tree).map((m) => m.nodeId)).toEqual([
      100, 102,
    ]);
  });
});

describe("getLatestMessageChain", () => {
  it("returns [] for an empty tree", () => {
    expect(getLatestMessageChain(new Map())).toEqual([]);
  });

  it("walks latestChildNodeId and excludes the system root", () => {
    let tree = upsertMessages(new Map(), [node(100, "user", null)]);
    tree = upsertMessages(tree, [node(101, "assistant", 100)]);
    const chain = getLatestMessageChain(tree);
    expect(chain.map((m) => m.nodeId)).toEqual([100, 101]);
  });
});

describe("setMessageAsLatest", () => {
  it("switches the active branch between sibling children", () => {
    let tree = upsertMessages(new Map(), [node(100, "user", null)]);
    tree = upsertMessages(tree, [node(101, "assistant", 100)]);
    // new sibling auto-becomes latest
    tree = upsertMessages(tree, [node(102, "assistant", 100)]);
    expect(getLatestMessageChain(tree).map((m) => m.nodeId)).toEqual([
      100, 102,
    ]);

    tree = setMessageAsLatest(tree, 101);
    expect(getLatestMessageChain(tree).map((m) => m.nodeId)).toEqual([
      100, 101,
    ]);
  });
});

describe("getMessageByMessageId", () => {
  it("finds a node by its backend messageId (not nodeId)", () => {
    const tree = upsertMessages(new Map(), [
      node(100, "user", null, { messageId: 42 }),
    ]);
    expect(getMessageByMessageId(tree, 42)!.nodeId).toBe(100);
    expect(getMessageByMessageId(tree, 999)).toBeUndefined();
  });
});

describe("getLastSuccessfulMessageId", () => {
  it("returns the last non-error messageId in the chain", () => {
    let tree = upsertMessages(new Map(), [
      node(100, "user", null, { messageId: 1 }),
    ]);
    tree = upsertMessages(tree, [
      node(101, "assistant", 100, { messageId: 2 }),
    ]);
    tree = upsertMessages(tree, [node(102, "error", 101, { messageId: 3 })]);

    expect(getLastSuccessfulMessageId(tree)).toBe(2);
  });
});
