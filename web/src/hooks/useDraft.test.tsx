import { renderHook } from "@testing-library/react";
import { useDraft } from "@/hooks/useDraft";

afterEach(() => sessionStorage.clear());

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
