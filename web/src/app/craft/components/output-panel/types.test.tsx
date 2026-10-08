import {
  getWebappState,
  type WebappState,
} from "@/app/craft/components/output-panel/types";

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
