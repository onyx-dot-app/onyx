import { beforeEach, describe, expect, it } from "@jest/globals";

import {
  buildImmediateMessages,
  getLatestMessageChain,
  SYSTEM_NODE_ID,
  upsertMessages,
} from "@/chat/messageTree";
import { useChatSessionStore } from "@/state/chatSessionStore";

function resetStore() {
  useChatSessionStore.setState({ currentSessionId: null, sessions: new Map() });
}

function treeWithTurn() {
  const { initialUserNode, initialAgentNode } = buildImmediateMessages(
    SYSTEM_NODE_ID,
    "hi",
    [],
  );
  return {
    tree: upsertMessages(new Map(), [initialUserNode, initialAgentNode], true),
    agentNodeId: initialAgentNode.nodeId,
  };
}

describe("chatSessionStore", () => {
  beforeEach(resetStore);

  it("ensureSession creates an empty session and never clobbers an existing one", () => {
    const store = useChatSessionStore.getState();
    store.ensureSession("a");
    const created = useChatSessionStore.getState().sessions.get("a");
    expect(created?.chatState).toBe("input");

    store.ensureSession("a");
    expect(useChatSessionStore.getState().sessions.get("a")).toBe(created);
  });

  it("updateSessionTree swaps the sessions map identity so selectors re-render", () => {
    const store = useChatSessionStore.getState();
    store.ensureSession("a");
    const before = useChatSessionStore.getState().sessions;

    store.updateSessionTree("a", treeWithTurn().tree);

    const after = useChatSessionStore.getState();
    expect(after.sessions).not.toBe(before);
    expect(
      getLatestMessageChain(after.sessions.get("a")!.messageTree),
    ).toHaveLength(2);
  });

  it("patchNode assigns a messageId without dropping the node", () => {
    const store = useChatSessionStore.getState();
    store.ensureSession("a");
    const { tree, agentNodeId } = treeWithTurn();
    store.updateSessionTree("a", tree);

    store.patchNode("a", agentNodeId, { messageId: 11 });

    const node = useChatSessionStore
      .getState()
      .sessions.get("a")!
      .messageTree.get(agentNodeId);
    expect(node?.messageId).toBe(11);
    expect(node?.type).toBe("assistant");
  });

  it("abortSession aborts the controller and resets chat state", () => {
    const store = useChatSessionStore.getState();
    store.ensureSession("a");
    const controller = new AbortController();
    store.setAbortController("a", controller);
    store.updateChatState("a", "streaming");

    store.abortSession("a");

    expect(controller.signal.aborted).toBe(true);
    const data = useChatSessionStore.getState().sessions.get("a");
    expect(data?.abortController).toBeNull();
    expect(data?.chatState).toBe("input");
  });
});
