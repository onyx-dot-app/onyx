import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/credentials/svc", () => ({
  submitCredential: jest.fn(),
}));

const { submitCredential } = jest.requireMock("@/lib/credentials/svc");

function renderNotion() {
  render(
    <CreateCredential
      sourceType={ValidSources.Notion}
      accessType="public"
      refresh={jest.fn()}
      onSwitch={jest.fn().mockResolvedValue(undefined)}
    />
  );
}

describe("CreateCredential", () => {
  beforeEach(() => {
    submitCredential.mockResolvedValue({
      message: "ok",
      isSuccess: true,
      credential: { id: 1 },
    });
  });

  it("sends the account's display name", async () => {
    const user = setupUser();
    renderNotion();

    await user.type(screen.getByTestId("notion_integration_token"), "secret");
    await user.type(screen.getByLabelText(/Name/), "  Team workspace ");
    await user.click(screen.getByRole("button", { name: /Create/ }));

    await waitFor(() =>
      expect(submitCredential).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Team workspace",
          credential_json: { notion_integration_token: "secret" },
        })
      )
    );
  });

  it("leaves a blank name out", async () => {
    const user = setupUser();
    renderNotion();

    await user.type(screen.getByTestId("notion_integration_token"), "secret");
    await user.click(screen.getByRole("button", { name: /Create/ }));

    await waitFor(() => expect(submitCredential).toHaveBeenCalled());
    expect(submitCredential.mock.calls[0][0]).not.toHaveProperty("name");
  });
});
