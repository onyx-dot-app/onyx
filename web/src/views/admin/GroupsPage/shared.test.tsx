// A member with an empty display name must show their email as the title.
// `??` only skips null, so an empty string left the row blank.
import { render, screen } from "@tests/setup/test-utils";
import { AccountType, UserStatus } from "@/lib/types";
import { makeBaseColumns } from "./shared";
import type { MemberRow } from "./types";

const labels = {
  name: "Name",
  accountType: "Account Type",
  manager: "Manager",
};

const row: MemberRow = {
  id: "1",
  email: "user@example.com",
  account_type: AccountType.STANDARD,
  is_admin: false,
  status: UserStatus.ACTIVE,
  is_active: true,
  is_scim_synced: false,
  craft_enabled: null,
  personal_name: "",
  created_at: null,
  updated_at: null,
  last_active: null,
  groups: [],
};

function renderNameCell(member: MemberRow) {
  const column = makeBaseColumns(labels).find(
    (c) => c.kind === "data" && c.id === "name"
  );
  if (column?.kind !== "data" || !column.cell) {
    throw new Error("name column not found");
  }
  render(<>{column.cell(undefined as never, member)}</>);
}

it("falls back to the email when personal_name is empty", () => {
  renderNameCell(row);
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
});

it("shows the name with the email below it when personal_name is set", () => {
  renderNameCell({ ...row, personal_name: "Ada Lovelace" });
  expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
});
