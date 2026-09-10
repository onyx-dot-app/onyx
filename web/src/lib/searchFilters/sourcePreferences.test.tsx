import { renderHook, act } from "@testing-library/react";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { useSourcePreferences } from "@/lib/searchFilters/hooks";
import { buildFilters } from "@/lib/searchFilters/utils";
import { getConfiguredSources } from "@/lib/sources";

beforeEach(() => {
  localStorage.clear();
});

function setup(availableSources: ValidSources[], ready = true) {
  const state: { selected: SourceMetadata[] } = { selected: [] };

  const hook = renderHook(
    ({ avail, ready: isReady }) =>
      useSourcePreferences({
        availableSources: avail,
        selectedSources: state.selected,
        setSelectedSources: (sources: SourceMetadata[]) => {
          state.selected = sources;
        },
        ready: isReady,
      }),
    { initialProps: { avail: availableSources, ready } }
  );

  return { hook, state };
}

function sourceNames(sources: SourceMetadata[]): string[] {
  return sources.map((s) => s.internalName).sort();
}

describe("useSourcePreferences — initialization", () => {
  test("all sources default to enabled on first load", () => {
    const { state } = setup([ValidSources.Notion, ValidSources.UserFile]);
    expect(sourceNames(state.selected)).toEqual(["notion", "user_file"]);
  });

  test("single source defaults to enabled", () => {
    const { state } = setup([ValidSources.Confluence]);
    expect(sourceNames(state.selected)).toEqual(["confluence"]);
  });
});

describe("useSourcePreferences — toggling", () => {
  test("toggling a source off removes it from selected", () => {
    const { hook, state } = setup([ValidSources.Notion, ValidSources.UserFile]);

    act(() => {
      hook.result.current.toggleSource("notion");
    });

    expect(sourceNames(state.selected)).toEqual(["user_file"]);
  });

  test("toggling persists preference to localStorage", () => {
    const { hook } = setup([ValidSources.Notion, ValidSources.UserFile]);

    act(() => {
      hook.result.current.toggleSource("notion");
    });

    const saved = JSON.parse(
      localStorage.getItem("selectedInternalSearchSources")!
    );
    expect(saved.sourcePreferences.notion).toBe(false);
    expect(saved.sourcePreferences.user_file).toBe(true);
  });
});

describe("useSourcePreferences — agent switching", () => {
  test("switching agents re-initializes with new sources enabled", () => {
    const { hook, state } = setup([ValidSources.Notion, ValidSources.Web]);
    expect(sourceNames(state.selected)).toEqual(["notion", "web"]);

    hook.rerender({
      avail: [ValidSources.Notion, ValidSources.UserFile],
      ready: true,
    });

    expect(sourceNames(state.selected)).toEqual(["notion", "user_file"]);
    expect(
      state.selected.find((s) => s.internalName === "web")
    ).toBeUndefined();
  });

  test("switching to default agent (all sources) shows everything", () => {
    const { hook, state } = setup([ValidSources.Notion]);
    expect(sourceNames(state.selected)).toEqual(["notion"]);

    hook.rerender({
      avail: [ValidSources.Notion, ValidSources.Web, ValidSources.Confluence],
      ready: true,
    });

    expect(sourceNames(state.selected)).toEqual([
      "confluence",
      "notion",
      "web",
    ]);
  });
});

describe("useSourcePreferences — localStorage persistence across agents", () => {
  test("saved preference honored when switching agents", () => {
    // Pre-seed localStorage: notion off, confluence on
    localStorage.setItem(
      "selectedInternalSearchSources",
      JSON.stringify({
        sourcePreferences: { notion: false, confluence: true },
      })
    );

    const { state } = setup([ValidSources.Notion, ValidSources.Confluence]);

    // Notion should be off (from saved prefs), confluence on
    expect(sourceNames(state.selected)).toEqual(["confluence"]);
  });

  test("new sources not in saved prefs default to enabled", () => {
    localStorage.setItem(
      "selectedInternalSearchSources",
      JSON.stringify({
        sourcePreferences: { notion: true },
      })
    );

    const { state } = setup([ValidSources.Notion, ValidSources.UserFile]);

    // user_file has no saved pref → defaults to enabled
    expect(sourceNames(state.selected)).toEqual(["notion", "user_file"]);
  });
});

describe("buildFilters — source_type payload", () => {
  const available = [ValidSources.Notion, ValidSources.UserFile];
  const configured = getConfiguredSources(available);

  test("every source enabled produces null source_type", () => {
    const { state } = setup(available);

    // The default selection. Sending it as a list would have the backend
    // report an applied filter and the UI name every connector it searched.
    const filters = buildFilters(state.selected, configured, [], null, []);
    expect(filters.source_type).toBeNull();
  });

  test("no sources produces null source_type", () => {
    const filters = buildFilters([], configured, [], null, []);
    expect(filters.source_type).toBeNull();
  });

  test("toggled-off source excluded from payload", () => {
    const { hook, state } = setup(available);

    act(() => {
      hook.result.current.toggleSource("notion");
    });

    const filters = buildFilters(state.selected, configured, [], null, []);
    expect(filters.source_type).toEqual(["user_file"]);
  });

  test("selection covering an unknown universe still filters", () => {
    const { state } = setup(available);

    // No universe to compare against — send what is selected rather than
    // silently widening the search to everything.
    const filters = buildFilters(state.selected, [], [], null, []);
    expect(filters.source_type?.sort()).toEqual(["notion", "user_file"]);
  });
});

describe("useSourcePreferences — readiness", () => {
  test("an unsettled list does not initialise preferences", () => {
    const { hook, state } = setup([ValidSources.Notion], false);

    expect(state.selected).toEqual([]);
    expect(hook.result.current.sourcesInitialized).toBe(false);
    expect(localStorage.getItem("selectedInternalSearchSources")).toBeNull();
  });

  test("initialising waits for the list to settle", () => {
    const { hook, state } = setup([ValidSources.Notion], false);
    expect(state.selected).toEqual([]);

    hook.rerender({ avail: [ValidSources.Notion], ready: true });

    expect(sourceNames(state.selected)).toEqual(["notion"]);
    expect(hook.result.current.sourcesInitialized).toBe(true);
  });

  test("a partial list is never persisted as the choice", () => {
    // The connector fetch has only returned one of two sources so far.
    const { hook, state } = setup([ValidSources.Notion], false);
    expect(localStorage.getItem("selectedInternalSearchSources")).toBeNull();

    // It settles, and the complete set arrives together with readiness.
    hook.rerender({
      avail: [ValidSources.Notion, ValidSources.Confluence],
      ready: true,
    });

    expect(sourceNames(state.selected)).toEqual(["confluence", "notion"]);
    const saved = JSON.parse(
      localStorage.getItem("selectedInternalSearchSources")!
    );
    expect(Object.keys(saved.sourcePreferences).sort()).toEqual([
      "confluence",
      "notion",
    ]);
  });
});
