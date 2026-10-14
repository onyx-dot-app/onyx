import { render, screen, setupUser } from "@tests/setup/test-utils";
import TurnOutputCards from "@/app/craft/components/TurnOutputCards";
import type { OutputCard } from "@/app/craft/types/streamingTypes";

const file: OutputCard = {
  id: "report",
  kind: "file",
  path: "outputs/reports/summary.md",
  name: "summary.md",
  turn_index: 0,
  revision: 1,
  size_bytes: 20,
  deleted: false,
  viewed_revision: null,
};

// Compact output actions.
test("opens a file with the keyboard and retains its folder context", async () => {
  const onOpen = jest.fn();
  render(
    <TurnOutputCards outputs={[file]} onOpen={onOpen} onShowAll={jest.fn()} />
  );
  expect(screen.getByText("MD · reports")).toBeInTheDocument();
  const user = setupUser();
  await user.tab();
  await user.keyboard("{Enter}");
  expect(onOpen).toHaveBeenCalledWith(file);
});

test("limits cards to three and exposes the full turn through one action", async () => {
  const outputs = Array.from({ length: 5 }, (_, index) => ({
    ...file,
    id: String(index),
    name: `report-${index}.md`,
    path: `outputs/report-${index}.md`,
  }));
  const onShowAll = jest.fn();
  render(
    <TurnOutputCards
      outputs={outputs}
      onOpen={jest.fn()}
      onShowAll={onShowAll}
    />
  );
  expect(screen.getAllByRole("button")).toHaveLength(4);
  expect(
    screen.queryByRole("button", { name: "report-3.md" })
  ).not.toBeInTheDocument();
  await setupUser().click(
    screen.getByRole("button", { name: "View all 5 outputs" })
  );
  expect(onShowAll).toHaveBeenCalledTimes(1);
});

test("keeps deleted outputs in history without an open action", () => {
  render(
    <TurnOutputCards
      outputs={[{ ...file, deleted: true }]}
      onOpen={jest.fn()}
      onShowAll={jest.fn()}
    />
  );
  expect(screen.getByRole("group", { name: file.name })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
  expect(screen.getByText("No longer available")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("opens the app card through the same action contract", async () => {
  const app: OutputCard = {
    ...file,
    id: "app",
    kind: "app",
    path: ".",
    name: "Todo app",
  };
  const onOpen = jest.fn();
  render(
    <TurnOutputCards outputs={[app]} onOpen={onOpen} onShowAll={jest.fn()} />
  );
  expect(screen.getByText("App")).toBeInTheDocument();
  await setupUser().click(
    screen.getByRole("button", { name: "Preview your app" })
  );
  expect(onOpen).toHaveBeenCalledWith(app);
});
