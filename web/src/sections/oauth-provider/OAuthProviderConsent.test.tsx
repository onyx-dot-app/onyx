import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import OAuthProviderConsent from "@/sections/oauth-provider/OAuthProviderConsent";
import { submitOAuthProviderConsent } from "@/lib/oauth-provider/api";

jest.mock("@/lib/oauth-provider/api", () => ({
  submitOAuthProviderConsent: jest.fn(),
}));

const submit = jest.mocked(submitOAuthProviderConsent);
const requestId = "a".repeat(43);
const details = {
  client_name: "Onyx test client",
  redirect_origin: "http://127.0.0.1:9876",
  account_email: "user@example.com",
  workspace_name: "Onyx workspace",
  scopes: ["read:search"],
  csrf_token: "c".repeat(43),
};

beforeEach(() => {
  submit.mockReset();
  submit.mockImplementation(() => new Promise<string>(() => {}));
});

afterEach(() => jest.restoreAllMocks());

test.each(["allow", "deny"] as const)(
  "requires an explicit %s decision",
  async (decision) => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(details)));
    const user = setupUser();

    render(<OAuthProviderConsent requestId={requestId} userId="owner" />);

    await screen.findByText("Allow Onyx test client to search Onyx?");
    expect(submit).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", {
        name: decision === "allow" ? "Allow access" : "Deny",
      })
    );
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith(
      requestId,
      details.csrf_token,
      decision
    );
    await user.click(screen.getByRole("button", { name: "Deny" }));
    expect(submit).toHaveBeenCalledTimes(1);
  }
);

test("explains failure without retrying an uncertain approval", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(details)));
  submit.mockRejectedValue(new Error("connection lost"));
  const user = setupUser();

  render(<OAuthProviderConsent requestId={requestId} userId="owner" />);

  await user.click(await screen.findByRole("button", { name: "Allow access" }));
  await screen.findByRole("alert");
  expect(
    screen.getByText(
      "Authorization could not finish. Start again from your app."
    )
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Allow access" }));
  expect(submit).toHaveBeenCalledTimes(1);
});

test("offers retry when the request service is unavailable", async () => {
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(new Response("{}", { status: 503 }));
  const user = setupUser();

  render(<OAuthProviderConsent requestId={requestId} userId="owner" />);

  await screen.findByRole("alert");
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(details)));
  await user.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Allow access" })
    ).toBeInTheDocument()
  );
  expect(submit).not.toHaveBeenCalled();
});

test("renders client-supplied names as text", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        ...details,
        client_name: "<img src=x onerror=alert(1)>",
      })
    )
  );

  const { container } = render(
    <OAuthProviderConsent requestId={requestId} userId="owner" />
  );

  await screen.findByText("Allow <img src=x onerror=alert(1)> to search Onyx?");
  expect(container.querySelector("img")).toBeNull();
});
