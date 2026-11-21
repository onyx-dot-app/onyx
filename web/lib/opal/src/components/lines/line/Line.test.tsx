import { render, screen, waitFor } from "@tests/setup/test-utils";
import { Line } from "@opal/components";
import { SvgEdit } from "@opal/icons";

// jsdom's setup reduces motion, so a swap would skip its animation. With
// motion on, a swap keeps showing the old title until its exit ends, which
// never happens in jsdom.
let motion: jest.SpyInstance;
beforeEach(() => {
  motion = jest.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: false,
        media: query,
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
      }) as unknown as MediaQueryList
  );
});
afterEach(() => motion.mockRestore());

test("a new title with the same key updates in place", async () => {
  const view = render(
    <Line icon={SvgEdit} title="Writing a file" titleKey="live" />
  );
  const title = screen.getByText("Writing a file");
  view.rerender(<Line icon={SvgEdit} title="Writing a.py" titleKey="live" />);
  await waitFor(() => expect(title).toHaveTextContent("Writing a.py"));
  expect(title).toBeInTheDocument();
});

test("a new key swaps the title", () => {
  const view = render(
    <Line icon={SvgEdit} title="Writing a.py" titleKey="live" />
  );
  view.rerender(<Line icon={SvgEdit} title="Edited 1 file" titleKey="done" />);
  // The old title leaves through the swap's exit first.
  expect(screen.getByText("Writing a.py")).toBeInTheDocument();
  expect(screen.queryByText("Edited 1 file")).not.toBeInTheDocument();
});
