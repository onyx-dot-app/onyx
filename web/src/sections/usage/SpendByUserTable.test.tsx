import { fireEvent, render, screen } from "@tests/setup/test-utils";
import SpendByUserTable from "@/sections/usage/SpendByUserTable";

test("opens a user from the keyboard", () => {
  const onSelectUser = jest.fn();

  render(
    <SpendByUserTable
      users={[
        {
          email: "ada@example.com",
          totals: {
            input_tokens: 1_000,
            output_tokens: 200,
            cache_read_tokens: 100,
            cost_cents: 25,
          },
          records: [],
        },
      ]}
      onSelectUser={onSelectUser}
    />
  );

  const row = screen.getByRole("row", {
    name: "View usage details for ada@example.com",
  });

  expect(
    screen.getByRole("columnheader", { name: "Tokens" })
  ).toBeInTheDocument();
  expect(screen.getByText("1 user")).toBeInTheDocument();

  row.focus();
  fireEvent.keyDown(row, { key: "Enter" });

  expect(onSelectUser).toHaveBeenCalledWith("ada@example.com");
});
