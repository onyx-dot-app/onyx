import { act, render, screen } from "@tests/setup/test-utils";
import { FilePreviewLoading } from "@/app/craft/components/output-panel/FilePreviewLoading";

afterEach(() => jest.useRealTimers());

it("keeps fast loads quiet and labels the delayed indicator for screen readers", () => {
  jest.useFakeTimers();
  render(<FilePreviewLoading />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  act(() => jest.advanceTimersByTime(299));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  act(() => jest.advanceTimersByTime(1));
  expect(screen.getByRole("status")).toHaveAccessibleName(/Loading/);
  expect(screen.queryByText(/Loading file/)).not.toBeInTheDocument();
});

it("clears the delay when loading finishes early", () => {
  jest.useFakeTimers();
  const view = render(<FilePreviewLoading />);
  view.unmount();
  expect(jest.getTimerCount()).toBe(0);
});
