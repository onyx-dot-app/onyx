import { render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import AuthenticationAccountCard from "@/views/admin/connectors/AddConnectorPage/components/AuthenticationAccountCard";
import type { SimilarCredential } from "@/lib/credentials/types";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "owner" }, permissions: [] }),
}));

const CREDENTIAL: SimilarCredential = {
  id: 7,
  name: "Prod Confluence",
  source: ValidSources.Confluence,
  credential_json: {},
  admin_public: false,
  groups: [],
  user_id: "owner",
  user_email: "owner@example.com",
  user_personal_name: null,
  time_created: "2026-10-01T00:00:00Z",
  time_updated: "2026-10-01T00:00:00Z",
  is_owner: true,
  usages: [],
};

function renderCard(overrides: Partial<SimilarCredential> = {}) {
  const props = {
    onSelect: jest.fn(),
    onDeselect: jest.fn(),
    onRename: jest.fn().mockResolvedValue(undefined),
  };
  render(
    <AuthenticationAccountCard
      credential={{ ...CREDENTIAL, ...overrides }}
      source={ValidSources.Confluence}
      sourceName="Confluence"
      selected={false}
      selectable
      onSelect={props.onSelect}
      onDeselect={props.onDeselect}
      onDelete={jest.fn()}
      detailsOpen={false}
      onDetailsOpenChange={jest.fn()}
      onRename={props.onRename}
      checkReport={null}
      onRerunChecks={jest.fn().mockResolvedValue(undefined)}
      groupsLocked={false}
      onUpdateSharing={jest.fn()}
    />
  );
  return props;
}

describe("AuthenticationAccountCard rename", () => {
  it("renames the account in place without picking it", async () => {
    const user = userEvent.setup({ delay: null });
    const { onSelect, onRename } = renderCard();

    await user.click(screen.getByText("Prod Confluence"));
    const input = screen.getByDisplayValue("Prod Confluence");
    await user.clear(input);
    await user.type(input, "Staging Confluence{Enter}");

    await waitFor(() =>
      expect(onRename).toHaveBeenCalledWith("Staging Confluence")
    );
    expect(screen.getByText("Staging Confluence")).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("starts a rename from the pencil without picking the account", async () => {
    const user = userEvent.setup({ delay: null });
    const { onSelect } = renderCard();

    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByDisplayValue("Prod Confluence")).toHaveFocus();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not offer a rename to a user who cannot edit the account", () => {
    renderCard({ is_owner: false, user_id: "someone-else" });

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});
