import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import TokenLimitSection from "@/views/admin/GroupsPage/TokenLimitSection";
import type { TokenLimit } from "@/views/admin/GroupsPage/TokenLimitSection";

function TokenLimitSectionHarness() {
  const [limits, setLimits] = useState<TokenLimit[]>([
    { tokenBudget: null, periodDays: null, costBudgetDollars: null },
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
