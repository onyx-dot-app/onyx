import { renderHook, act } from "@testing-library/react";
import { ValidSources } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { useSourcePreferences } from "@/lib/hooks";
import { buildFilters } from "@/lib/search/utils";

beforeEach(() => {
  localStorage.clear();
});

function setup(availableSources: ValidSources[]) {
  const state: { selected: SourceMetadata[] } = { selected: [] };

  const hook = renderHook(
    ({ avail }) =>
      useSourcePreferences({
        availableSources: avail,
        selectedSources: state.selected,
        setSelectedSources: (sources: SourceMetadata[]) => {
          state.selected = sources;
        },
      }),
    { initialProps: { avail: availableSources } }
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
  test("enabled sources produce a source_type array", () => {
    const { state } = setup([ValidSources.Notion, ValidSources.UserFile]);

    const filters = buildFilters(state.selected, [], null, []);
    expect(filters.source_type?.sort()).toEqual(["notion", "user_file"]);
  });

  test("no sources produces null source_type", () => {
    const filters = buildFilters([], [], null, []);
    expect(filters.source_type).toBeNull();
  });

  test("toggled-off source excluded from payload", () => {
    const { hook, state } = setup([ValidSources.Notion, ValidSources.UserFile]);

    act(() => {
      hook.result.current.toggleSource("notion");
    });

    const filters = buildFilters(state.selected, [], null, []);
    expect(filters.source_type).toEqual(["user_file"]);
  });
});
