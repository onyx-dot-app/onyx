import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import { useSourceSelection } from "@/hooks/useSourceSelection";
import { appStorage } from "@/state/storage";

jest.mock("@/state/storage");
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

const STORAGE_KEY = "onyx.chat.source_preferences.https://example.test";

function saved(): Record<string, boolean> | undefined {
  const raw = appStorage.getString(STORAGE_KEY);
  return raw
    ? (JSON.parse(raw) as { sourcePreferences: Record<string, boolean> })
        .sourcePreferences
    : undefined;
}

function render(initial: string[]) {
  return renderHook((sources: string[]) => useSourceSelection(sources), {
    initialProps: initial,
  });
}

describe("useSourceSelection", () => {
  beforeEach(() => {
    appStorage.clearAll();
  });

  it("starts with every available source on", () => {
    const { result } = render(["notion", "web"]);
    expect(result.current.selectedSources).toEqual(["notion", "web"]);
    expect(result.current.initialized).toBe(true);
  });

  it("stays uninitialized while there is no catalogue to reconcile", () => {
    const { result } = render([]);
    expect(result.current.initialized).toBe(false);
    expect(result.current.selectedSources).toEqual([]);
  });

  it("writes nothing until the user chooses something", () => {
    render(["notion", "web"]);
    expect(saved()).toBeUndefined();
  });

  it("remembers a source switched off", () => {
    const { result } = render(["notion", "web"]);
    act(() => result.current.toggleSource("notion"));

    expect(result.current.selectedSources).toEqual(["web"]);
    expect(saved()).toEqual({ notion: false, web: true });
  });

  it("restores the saved choice on a later mount", () => {
    appStorage.set(
      STORAGE_KEY,
      JSON.stringify({ sourcePreferences: { notion: false, web: true } }),
    );
    const { result } = render(["notion", "web"]);
    expect(result.current.selectedSources).toEqual(["web"]);
  });

  it("switches a newly connected source on despite an older snapshot", () => {
    appStorage.set(
      STORAGE_KEY,
      JSON.stringify({ sourcePreferences: { notion: false } }),
    );
    const { result } = render(["notion", "jira"]);
    expect(result.current.selectedSources).toEqual(["jira"]);
  });

  it("re-derives when the catalogue changes under it", () => {
    const { result, rerender } = render(["notion", "web"]);
    act(() => result.current.toggleSource("notion"));

    // An agent scoped to other sources — the old pick can't leak into the new list.
    rerender(["jira"]);
    expect(result.current.selectedSources).toEqual(["jira"]);

    rerender(["notion", "web"]);
    expect(result.current.selectedSources).toEqual(["web"]);
  });

  it("turns everything off and back on", () => {
    const { result } = render(["notion", "web"]);

    act(() => result.current.disableAllSources());
    expect(result.current.selectedSources).toEqual([]);
    expect(saved()).toEqual({ notion: false, web: false });

    act(() => result.current.enableAllSources());
    expect(result.current.selectedSources).toEqual(["notion", "web"]);
    expect(saved()).toEqual({ notion: true, web: true });
  });

  it("restores an explicit set", () => {
    const { result } = render(["notion", "web", "jira"]);
    act(() => result.current.setSources(["jira"]));

    expect(result.current.selectedSources).toEqual(["jira"]);
    expect(result.current.isSourceEnabled("jira")).toBe(true);
    expect(result.current.isSourceEnabled("web")).toBe(false);
  });

  it("scopes the snapshot to the instance it was made on", () => {
    const { result } = render(["notion", "web"]);
    act(() => result.current.toggleSource("notion"));

    expect(appStorage.getString(STORAGE_KEY)).toBeTruthy();
    expect(
      appStorage.getString("onyx.chat.source_preferences.https://other.test"),
    ).toBeUndefined();
  });

  it("ignores a source the agent can't reach", () => {
    const { result } = render(["notion"]);
    act(() => result.current.toggleSource("jira"));
    expect(result.current.selectedSources).toEqual(["notion"]);
  });

  it("keeps the session's choice when the write fails, rather than throwing at the caller", () => {
    /*
     * `commit` runs from an `onPress` handler and from the search coupling, and neither catches —
     * a throw here would reach the global error handler. The choice still holds for this session;
     * only its persistence is lost.
     */
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const failure = new Error("mmkv: no space left on device");
    const setSpy = jest.spyOn(appStorage, "set").mockImplementation(() => {
      throw failure;
    });

    const { result } = render(["notion", "web"]);
    expect(() =>
      act(() => result.current.toggleSource("notion")),
    ).not.toThrow();

    expect(result.current.selectedSources).toEqual(["web"]);
    expect(result.current.isSourceEnabled("notion")).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), failure);

    setSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("still initializes when the saved snapshot can't be read", () => {
    // The read runs during render, so a throw would take the composer down with it.
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const getSpy = jest
      .spyOn(appStorage, "getString")
      .mockImplementation(() => {
        throw new Error("mmkv: unreadable");
      });

    const { result } = render(["notion", "web"]);

    expect(result.current.initialized).toBe(true);
    expect(result.current.selectedSources).toEqual(["notion", "web"]);
    expect(warnSpy).toHaveBeenCalled();

    getSpy.mockRestore();
    warnSpy.mockRestore();
  });
});
