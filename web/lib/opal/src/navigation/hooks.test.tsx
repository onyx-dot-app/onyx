import { renderHook } from "@testing-library/react";
import { useSelectedLayoutSegments } from "next/navigation";
import { useRenderedPathname } from "@opal/navigation";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useSelectedLayoutSegments: jest.fn(),
}));

const mockSegments = useSelectedLayoutSegments as jest.MockedFunction<
  typeof useSelectedLayoutSegments
>;

test("names the rendered page under the base", () => {
  mockSegments.mockReturnValue(["language-models"]);
  const { result } = renderHook(() => useRenderedPathname("/admin"));
  expect(result.current).toBe("/admin/language-models");
});

test("skips route groups, which name no URL segment", () => {
  mockSegments.mockReturnValue(["(settings)", "theme"]);
  const { result } = renderHook(() => useRenderedPathname("/ee/admin"));
  expect(result.current).toBe("/ee/admin/theme");
});

test("is the base itself when the base page is rendered", () => {
  mockSegments.mockReturnValue([]);
  const { result } = renderHook(() => useRenderedPathname("/admin"));
  expect(result.current).toBe("/admin");
});
