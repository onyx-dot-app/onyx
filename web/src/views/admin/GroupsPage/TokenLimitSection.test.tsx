import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import TokenLimitSection from "@/views/admin/GroupsPage/TokenLimitSection";
import type { TokenLimit } from "@/views/admin/GroupsPage/TokenLimitSection";

function TokenLimitSectionHarness() {
  const [limits, setLimits] = useState<TokenLimit[]>([
    {
      tokenId: null,
      enabled: true,
      tokenBudget: null,
      periodDays: null,
      costBudgetDollars: null,
    },
  ]);

  return <TokenLimitSection limits={limits} onLimitsChange={setLimits} />;
}

test("accepts a cost limit with cents", async () => {
  const user = setupUser();
  render(<TokenLimitSectionHarness />);

  const costLimit = screen.getByPlaceholderText("Cost limit");
  await user.type(costLimit, "1.23");
  await user.click(screen.getByRole("button", { name: "Add Limit" }));

  expect(costLimit).toHaveValue("1.23");
  expect(screen.getAllByPlaceholderText("Cost limit")).toHaveLength(2);
});

test("enforces a positive cost limit", async () => {
  const user = setupUser();
  render(<TokenLimitSectionHarness />);

  const costLimit = screen.getByPlaceholderText("Cost limit");
  await user.type(costLimit, "0");

  expect(costLimit).toHaveValue("0.01");
});

test("enforces a positive token limit", async () => {
  const user = setupUser();
  render(<TokenLimitSectionHarness />);

  const tokenLimit = screen.getByPlaceholderText("Token limit (thousands)");
  await user.type(tokenLimit, "0");

  expect(tokenLimit).toHaveValue("1");
});
