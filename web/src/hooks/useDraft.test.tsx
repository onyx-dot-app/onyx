import { renderHook } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { useDraft, type DraftStorage } from "@/hooks/useDraft";

afterEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

test("a page unload writes the pending draft", () => {
  const { result } = renderHook(() => useDraft<string>({ key: "draft" }));
  result.current.save("Edited queued message");
  expect(sessionStorage.getItem("draft")).toBeNull();

  window.dispatchEvent(new Event("pagehide"));

  expect(sessionStorage.getItem("draft")).toBe(
    JSON.stringify("Edited queued message")
  );
});

test("a page unload does not restore a cleared draft", () => {
  const { result } = renderHook(() => useDraft<string>({ key: "draft" }));
  result.current.save("Sent message");
  result.current.clear();

  window.dispatchEvent(new Event("pagehide"));

  expect(sessionStorage.getItem("draft")).toBeNull();
});

test("switching storage reloads the entry and cancels the previous save", () => {
  sessionStorage.setItem("draft", JSON.stringify("Session draft"));
  localStorage.setItem("draft", JSON.stringify("Local draft"));
  const observed = jest.fn();
  const { result, rerender } = renderHook(
    ({ storage }: { storage: DraftStorage }) => {
      const draft = useDraft<string>({ key: "draft", storage });
      useLayoutEffect(() => {
        observed(draft.loaded, draft.draft);
      }, [draft.loaded, draft.draft, storage]);
      return draft;
    },
    { initialProps: { storage: "session" } }
  );

  result.current.save("Pending draft");
  observed.mockClear();
  rerender({ storage: "local" });
  window.dispatchEvent(new Event("pagehide"));

  expect(observed.mock.calls).toEqual([
    [false, null],
    [true, "Local draft"],
  ]);
  expect(sessionStorage.getItem("draft")).toBe(JSON.stringify("Session draft"));
});
