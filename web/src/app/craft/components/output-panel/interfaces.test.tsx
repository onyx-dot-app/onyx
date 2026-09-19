import {
  getWebappState,
  isWebappPreviewEnabled,
  type WebappState,
} from "@/app/craft/components/output-panel/interfaces";

describe("getWebappState", () => {
  test.each<{
    hasBeenReady: boolean;
    hasWebapp: boolean | null | undefined;
    expected: WebappState;
  }>([
    { hasBeenReady: true, hasWebapp: null, expected: "ready" },
    { hasBeenReady: false, hasWebapp: undefined, expected: "unknown" },
    { hasBeenReady: false, hasWebapp: null, expected: "unknown" },
    { hasBeenReady: false, hasWebapp: false, expected: "none" },
    { hasBeenReady: false, hasWebapp: true, expected: "starting" },
  ])(
    "returns $expected for ready=$hasBeenReady and hasWebapp=$hasWebapp",
    ({ hasBeenReady, hasWebapp, expected }) => {
      expect(getWebappState(hasBeenReady, hasWebapp)).toBe(expected);
    }
  );
});

describe("isWebappPreviewEnabled", () => {
  test.each<{
    state: WebappState;
    canQueryWebapp: boolean;
    expected: boolean;
  }>([
    { state: "unknown", canQueryWebapp: false, expected: false },
    { state: "ready", canQueryWebapp: false, expected: false },
    { state: "unknown", canQueryWebapp: true, expected: true },
    { state: "none", canQueryWebapp: true, expected: false },
    { state: "starting", canQueryWebapp: true, expected: true },
    { state: "ready", canQueryWebapp: true, expected: true },
  ])(
    "returns $expected for $state when queryable=$canQueryWebapp",
    ({ state, canQueryWebapp, expected }) => {
      expect(isWebappPreviewEnabled(state, canQueryWebapp)).toBe(expected);
    }
  );
});
