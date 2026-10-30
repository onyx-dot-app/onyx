import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/credentials/svc", () => ({
  submitCredential: jest.fn(),
}));

jest.mock("@/lib/tiers/hooks", () => ({
  ...jest.requireActual("@/lib/tiers/hooks"),
  useTierAtLeast: () => false,
}));

jest.mock("@/lib/hooks", () => ({
  useUserGroups: () => ({ data: [] }),
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

  function renderJsm() {
    render(
      <CreateCredential
        sourceType={ValidSources.JiraServiceManagement}
        accessType="private"
        refresh={jest.fn()}
        onSwitch={jest.fn().mockResolvedValue(undefined)}
      />
    );
  }

  it("blocks a JSM URL-only or partial-email submission", async () => {
    const user = setupUser();
    renderJsm();
    await user.type(
      screen.getByTestId("jsm_base_url"),
      "https://acme.atlassian.net"
    );
    const create = screen.getByRole("button", { name: /Create/ });
    await waitFor(() => expect(create).toBeDisabled());
    await user.type(screen.getByTestId("jsm_user_email"), "agent@example.com");
    await waitFor(() => expect(create).toBeDisabled());
  });

  it.each(["email", "bearer"])(
    "submits a complete JSM %s account",
    async (method) => {
      const user = setupUser();
      renderJsm();
      await user.type(
        screen.getByTestId("jsm_base_url"),
        "https://acme.atlassian.net"
      );
      const auth =
        method === "email"
          ? { jsm_user_email: "agent@example.com", jsm_api_token: "token" }
          : { jsm_bearer_token: "token" };
      for (const [field, value] of Object.entries(auth)) {
        await user.type(screen.getByTestId(field), value);
      }
      const create = screen.getByRole("button", { name: /Create/ });
      await waitFor(() => expect(create).toBeEnabled());
      await user.click(create);
      await waitFor(() =>
        expect(submitCredential).toHaveBeenCalledWith(
          expect.objectContaining({
            source: ValidSources.JiraServiceManagement,
            credential_json: expect.objectContaining({
              jsm_base_url: "https://acme.atlassian.net",
              ...auth,
            }),
          })
        )
      );
    }
  );
});
