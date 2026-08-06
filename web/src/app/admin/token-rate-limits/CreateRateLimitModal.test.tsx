import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import CreateRateLimitModal from "@/app/admin/token-rate-limits/CreateRateLimitModal";

beforeEach(() => {
  global.fetch = jest
    .fn()
    .mockResolvedValue({ ok: true, json: async () => [] } as Response);
});

test("requires a cost budget when no token budget is set", async () => {
  const onSubmit = jest.fn().mockResolvedValue(undefined);

  render(
    <CreateRateLimitModal isOpen setIsOpen={jest.fn()} onSubmit={onSubmit} />
  );

  const modal = screen.getByRole("dialog");
  const resetPeriod = screen.getByRole("textbox", { name: /Reset period/ });

  expect(modal).toHaveAttribute("data-width", "sm");
  expect(modal).toHaveAttribute("data-height", "fit");
  expect(resetPeriod).toHaveAttribute("type", "text");
  expect(resetPeriod).toHaveAttribute("inputmode", "numeric");
  expect(resetPeriod).toHaveValue("30");

  fireEvent.click(screen.getByRole("button", { name: "Create limit" }));

  expect(
    await screen.findByText("Enter a cost budget, a token budget, or both")
  ).toBeInTheDocument();
  expect(onSubmit).not.toHaveBeenCalled();
});

test("formats and submits a token-only budget", async () => {
  const onSubmit = jest.fn().mockResolvedValue(undefined);

  render(
    <CreateRateLimitModal isOpen setIsOpen={jest.fn()} onSubmit={onSubmit} />
  );

  const tokenBudget = screen.getByRole("textbox", {
    name: /Token budget/,
  });

  fireEvent.change(tokenBudget, {
    target: { value: "1500000000" },
  });

  expect(tokenBudget).toHaveValue("1,500,000,000");

  fireEvent.click(screen.getByRole("button", { name: "Create limit" }));

  await waitFor(() =>
    expect(onSubmit).toHaveBeenCalledWith(
      "global",
      720,
      1_500_000,
      null,
      undefined
    )
  );
});

test("rejects a cost budget that rounds below one cent", async () => {
  const onSubmit = jest.fn().mockResolvedValue(undefined);

  render(
    <CreateRateLimitModal isOpen setIsOpen={jest.fn()} onSubmit={onSubmit} />
  );

  fireEvent.change(screen.getByRole("textbox", { name: /Cost budget/ }), {
    target: { value: "0.001" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create limit" }));

  expect(
    await screen.findByText("Cost budget must be at least $0.01")
  ).toBeInTheDocument();
  expect(onSubmit).not.toHaveBeenCalled();
});

test("supports arrow-key navigation between scope options", async () => {
  render(
    <CreateRateLimitModal
      isOpen
      setIsOpen={jest.fn()}
      onSubmit={jest.fn().mockResolvedValue(undefined)}
    />
  );

  const workspace = screen.getByRole("radio", { name: "Workspace" });
  const perUser = screen.getByRole("radio", { name: "Per user" });

  workspace.focus();
  fireEvent.keyDown(workspace, { key: "ArrowRight" });

  await waitFor(() => expect(perUser).toHaveAttribute("aria-checked", "true"));
  expect(perUser).toHaveFocus();
});
