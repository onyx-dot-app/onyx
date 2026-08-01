import { render, screen, setupUser } from "@tests/setup/test-utils";
import CreateRateLimitModal from "@/app/admin/token-rate-limits/CreateRateLimitModal";

test("requires at least one enforcement budget", async () => {
  const user = setupUser();
  const onSubmit = jest.fn().mockResolvedValue(undefined);

  render(
    <CreateRateLimitModal isOpen setIsOpen={jest.fn()} onSubmit={onSubmit} />
  );

  await user.type(screen.getByLabelText("Time Window (UTC Days)"), "1");
  await user.click(screen.getByRole("button", { name: "Create" }));

  expect(
    await screen.findByText("Set a token budget and/or a cost budget")
  ).toBeInTheDocument();
  expect(onSubmit).not.toHaveBeenCalled();
});
