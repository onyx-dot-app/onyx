/** @jest-environment jsdom */

import type * as RunStatus from "@/lib/chat/runStatus";

const KEY = "onyx:unseen-runs:v1";

/** A fresh copy of the module, as a page load gets. */
function loadRunStatus(): typeof RunStatus {
  let loaded: typeof RunStatus | undefined;
  jest.isolateModules(() => {
    loaded = jest.requireActual<typeof RunStatus>("@/lib/chat/runStatus");
  });
  if (!loaded) throw new Error("runStatus did not load");
  return loaded;
}

beforeEach(() => sessionStorage.clear());

describe("unseen runs across reloads", () => {
  test("a record the user has not viewed survives a reload", () => {
    loadRunStatus().useUnseenRuns.getState().markUnseen("chat-1", "done");

    const reloaded = loadRunStatus().useUnseenRuns.getState();
    expect(reloaded.unseen.get("chat-1")).toBe("done");
  });

  test("a viewed chat stays seen after a reload", () => {
    const { useUnseenRuns } = loadRunStatus();
    useUnseenRuns.getState().markUnseen("chat-1", "failed");
    useUnseenRuns.getState().markSeen("chat-1");

    expect(loadRunStatus().useUnseenRuns.getState().unseen.size).toBe(0);
  });

  test("only the newest 50 records are kept", () => {
    const { useUnseenRuns } = loadRunStatus();
    for (let index = 0; index < 55; index++)
      useUnseenRuns.getState().markUnseen(`chat-${index}`, "done");

    const kept = loadRunStatus().useUnseenRuns.getState().unseen;
    expect(kept.size).toBe(50);
    expect(kept.has("chat-4")).toBe(false);
    expect(kept.has("chat-54")).toBe(true);
  });

  test("clearing all runs removes active and persisted markers", () => {
    const { useUnseenRuns } = loadRunStatus();
    useUnseenRuns.getState().markUnseen("chat-1", "failed");
    useUnseenRuns.getState().clearAll();
    expect(useUnseenRuns.getState().unseen.size).toBe(0);
    expect(loadRunStatus().useUnseenRuns.getState().unseen.size).toBe(0);
  });

  test("bad saved data loads as no records", () => {
    sessionStorage.setItem(KEY, '[["chat-1","exploded"],42,"x"]');
    expect(loadRunStatus().useUnseenRuns.getState().unseen.size).toBe(0);

    sessionStorage.setItem(KEY, "not json");
    expect(loadRunStatus().useUnseenRuns.getState().unseen.size).toBe(0);
  });
});
