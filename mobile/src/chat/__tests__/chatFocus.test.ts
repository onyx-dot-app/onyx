import { describe, expect, it } from "@jest/globals";

import { deriveFocus } from "@/chat/chatFocus";

describe("deriveFocus", () => {
  it("maps / to the new-chat focus", () => {
    expect(deriveFocus("/")).toEqual({
      kind: "new",
      sessionId: null,
      projectId: null,
    });
  });

  it("maps /chat/<id> to a chat focus", () => {
    expect(deriveFocus("/chat/abc-123")).toEqual({
      kind: "chat",
      sessionId: "abc-123",
      projectId: null,
    });
  });

  it("maps /projects/<n> to a project focus", () => {
    expect(deriveFocus("/projects/7")).toEqual({
      kind: "project",
      sessionId: null,
      projectId: 7,
    });
  });

  it("rejects a non-numeric project id", () => {
    expect(deriveFocus("/projects/abc")).toBeNull();
  });

  it("rejects an empty chat or project id", () => {
    expect(deriveFocus("/chat/")).toBeNull();
    expect(deriveFocus("/projects/")).toBeNull();
  });

  it("returns null for non-surface routes (e.g. the agents gallery)", () => {
    expect(deriveFocus("/agents")).toBeNull();
    expect(deriveFocus("/settings/profile")).toBeNull();
  });
});
