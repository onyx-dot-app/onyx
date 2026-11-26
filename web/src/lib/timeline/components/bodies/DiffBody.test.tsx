import { render, screen } from "@tests/setup/test-utils";
import { DiffBody } from "@/lib/timeline/components/bodies/DiffBody";

const lines = (count: number) =>
  Array.from({ length: count }, (_, i) => `line ${i}`).join("\n");

test("the view toggle has an accessible name, and the counts read in the singular", () => {
  render(<DiffBody title="a.py" oldText="a\nb" newText="a\nc" />);
  expect(
    screen.getByRole("button", { name: "Switch to side-by-side" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("group", { name: "1 addition, 1 deletion" })
  ).toBeInTheDocument();
});

test("a large pure addition stays unified, a large replace opens side by side", () => {
  const view = render(
    <DiffBody title="new.py" oldText="" newText={lines(30)} />
  );
  expect(
    screen.getByRole("button", { name: "Switch to side-by-side" })
  ).toBeInTheDocument();
  view.unmount();

  render(
    <DiffBody
      title="a.py"
      oldText={lines(30)}
      newText={lines(30).replaceAll("line", "row")}
    />
  );
  expect(
    screen.getByRole("button", { name: "Switch to unified" })
  ).toBeInTheDocument();
});

test("a note-only panel has no view toggle", () => {
  render(
    <DiffBody
      title="x"
      lines={[{ type: "header", content: "500 more lines" }]}
    />
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("line counts are compact in the active locale", () => {
  render(
    <DiffBody
      title="a.py"
      lines={[{ type: "added", content: "x" }]}
      counts={{ added: 1200, removed: 0 }}
    />
  );
  expect(screen.getByText("+1.2K")).toBeInTheDocument();
});

test("a long title is a block, so it cuts with an ellipsis before the counts", () => {
  const path =
    "src/components/settings/notifications/NotificationPreferences.tsx";
  render(<DiffBody title={path} oldText="a" newText="b" />);
  const title = screen.getByText(path);
  // `truncate` clips only a block box; an inline span would overflow.
  expect(title.tagName).toBe("P");
  expect(title).toHaveClass("truncate");
});
