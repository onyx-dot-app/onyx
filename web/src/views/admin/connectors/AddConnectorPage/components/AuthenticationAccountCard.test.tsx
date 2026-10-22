import { render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
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
  usable: true,
  refusal_reason: null,
};

type CardProps = ComponentProps<typeof AuthenticationAccountCard>;

function renderCard(
  overrides: Partial<SimilarCredential> = {},
  cardProps: Partial<CardProps> = {}
) {
  const props = {
    onSelect: jest.fn(),
    onDeselect: jest.fn(),
    onSaveAccount: jest
      .fn()
      .mockResolvedValue({ admin_public: false, groups: [] }),
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
      checkReport={null}
      groupsLocked={false}
      onSaveAccount={props.onSaveAccount}
      {...cardProps}
    />
  );
  return props;
}

describe("AuthenticationAccountCard checks", () => {
  it("says when the last run failed to run", () => {
    renderCard(
      {},
      {
        detailsOpen: true,
        checkReport: {
          credential_id: 7,
          connector_id: null,
          run_status: "failed_to_run",
          run_started_at: null,
          report: null,
          progress: null,
          time_updated: "2026-10-01T00:00:00Z",
        },
      }
    );
    expect(screen.getByText("Checks Failed to Run")).toBeInTheDocument();
  });
});

describe("AuthenticationAccountCard unusable account", () => {
  it("shows why a shared account cannot be picked, and does not pick it", async () => {
    const user = userEvent.setup({ delay: null });
    const reason = "Credential 7 is shared with you.";
    const { onSelect } = renderCard(
      { usable: false, refusal_reason: reason },
      { selectable: false }
    );

    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByText("Not Available")).toBeInTheDocument();
    await user.click(screen.getByText(reason));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("shows why a selected account can no longer be used", () => {
    const reason = "Credential 7 is shared with you.";
    renderCard(
      { usable: false, refusal_reason: reason },
      { selected: true, selectable: true }
    );

    expect(screen.getByText(reason)).toBeInTheDocument();
  });
});

describe("AuthenticationAccountCard rename", () => {
  it("renames the account in place without picking it", async () => {
    const user = userEvent.setup({ delay: null });
    const { onSelect, onSaveAccount } = renderCard();

    await user.click(screen.getByText("Prod Confluence"));
    const input = screen.getByDisplayValue("Prod Confluence");
    await user.clear(input);
    await user.type(input, "Staging Confluence{Enter}");

    // Through the sharing route, with the sharing as stored.
    await waitFor(() =>
      expect(onSaveAccount).toHaveBeenCalledWith({
        admin_public: false,
        groups: [],
        name: "Staging Confluence",
      })
    );
    expect(screen.getByText("Staging Confluence")).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("sends a rename made during another only after it, with the newest name shown", async () => {
    const user = userEvent.setup({ delay: null });
    const { onSaveAccount } = renderCard();
    let finishFirst: () => void = () => {};
    onSaveAccount.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = () => resolve({ admin_public: false, groups: [] });
        })
    );

    const rename = async (from: string, to: string) => {
      await user.click(screen.getByText(from));
      const input = screen.getByDisplayValue(from);
      await user.clear(input);
      await user.type(input, `${to}{Enter}`);
    };
    await rename("Prod Confluence", "First");
    await rename("First", "Second");

    // The second waits for the first.
    expect(onSaveAccount).toHaveBeenCalledTimes(1);
    finishFirst();
    await waitFor(() => expect(onSaveAccount).toHaveBeenCalledTimes(2));
    expect(onSaveAccount).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: "Second" })
    );
    expect(screen.getByText("Second")).toBeInTheDocument();
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
