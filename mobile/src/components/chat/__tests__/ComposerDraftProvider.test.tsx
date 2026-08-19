import { describe, expect, it } from "@jest/globals";
import { useContext } from "react";
import { act, renderHook } from "@testing-library/react-native";

import {
  ComposerDraftContext,
  ComposerDraftProvider,
} from "@/components/chat/ComposerDraftProvider";

function useCtx() {
  const ctx = useContext(ComposerDraftContext);
  if (!ctx) throw new Error("missing provider");
  return ctx;
}

function setup() {
  return renderHook(() => useCtx(), { wrapper: ComposerDraftProvider });
}

describe("ComposerDraftProvider", () => {
  it("keeps text + clientIds isolated per draftKey", () => {
    const { result } = setup();
    act(() => {
      result.current.setText("a", "hello");
      result.current.addFiles("a", ["f1"]);
    });
    act(() => result.current.setText("b", "world"));

    expect(result.current.drafts["a"]).toEqual({
      text: "hello",
      clientIds: ["f1"],
    });
    expect(result.current.drafts["b"]).toEqual({
      text: "world",
      clientIds: [],
    });
  });

  it("setText keeps the clientIds array reference stable (memoized chips skip a keystroke)", () => {
    const { result } = setup();
    act(() => result.current.addFiles("a", ["f1"]));
    const before = result.current.drafts["a"]!.clientIds;
    act(() => result.current.setText("a", "typing…"));
    expect(result.current.drafts["a"]!.clientIds).toBe(before);
  });

  it("addFiles dedupes; removeFile drops one id", () => {
    const { result } = setup();
    act(() => {
      result.current.addFiles("a", ["f1", "f2"]);
      result.current.addFiles("a", ["f1", "f3"]);
    });
    expect(result.current.drafts["a"]!.clientIds).toEqual(["f1", "f2", "f3"]);
    act(() => result.current.removeFile("a", "f2"));
    expect(result.current.drafts["a"]!.clientIds).toEqual(["f1", "f3"]);
  });

  it("consume clears the whole draft; consumeAttachments keeps the text", () => {
    const { result } = setup();
    act(() => {
      result.current.setText("a", "keep me");
      result.current.addFiles("a", ["f1"]);
    });
    act(() => result.current.consumeAttachments("a"));
    expect(result.current.drafts["a"]).toEqual({
      text: "keep me",
      clientIds: [],
    });

    act(() => {
      result.current.setText("b", "gone");
      result.current.consume("b");
    });
    expect(result.current.drafts["b"]).toBeUndefined();
  });
});
