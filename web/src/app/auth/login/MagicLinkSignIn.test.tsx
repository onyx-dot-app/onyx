/**
 * @jest-environment jsdom
 */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MagicLinkSignIn from "@/app/auth/login/MagicLinkSignIn";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

async function requestLink(address: string): Promise<void> {
  const user = setupUser();
  await user.type(screen.getByTestId("magic-link-email"), address);
  await user.click(screen.getByRole("button", { name: "Get a link by email" }));
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("MagicLinkSignIn", () => {
  test("asks for a link and says where it went", async () => {
    // Mock POST /api/auth/magic-link/request
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(202, { email: "bob@acme.com" }));

    render(<MagicLinkSignIn nextUrl="/app?q=1" />);
    await requestLink("  Bob@Acme.com ");

    // Announced: the confirmation lands in a status region.
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Check your email"
    );
    expect(
      screen.getByText(
        "We sent a sign-in link to bob@acme.com. It works once and expires in 15 minutes."
      )
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/magic-link/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: "bob@acme.com",
        next_url: "/app?q=1",
        start_new_team: false,
      }),
    });
  });

  test("carries the start-a-new-team choice", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(202, { email: "bob@acme.com" }));

    render(<MagicLinkSignIn nextUrl={null} startNewTeam />);
    await requestLink("bob@acme.com");

    await screen.findByText("Check your email");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({
      email: "bob@acme.com",
      next_url: null,
      start_new_team: true,
    });
  });

  test("starts from a supplied address and can send it as it is", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(202, { email: "bob@acme.com" }));
    const user = setupUser();

    render(<MagicLinkSignIn nextUrl={null} defaultEmail="bob@acme.com" />);
    expect(screen.getByTestId("magic-link-email")).toHaveValue("bob@acme.com");
    await user.click(
      screen.getByRole("button", { name: "Get a link by email" })
    );

    await screen.findByText("Check your email");
    const init = fetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(String(init?.body)).email).toBe("bob@acme.com");
  });

  test("goes back to the form for a different address", async () => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(202, { email: "bob@acme.com" }));
    const user = setupUser();

    render(<MagicLinkSignIn nextUrl={null} />);
    await requestLink("bob@acme.com");
    await user.click(
      await screen.findByRole("button", { name: "Use a different email" })
    );

    expect(screen.getByTestId("magic-link-email")).toBeInTheDocument();
  });

  test.each([
    [403, "PLAYGROUND_FREE_MAIL", "Use your work email."],
    [
      403,
      "MAGIC_LINK_USE_SSO",
      "Sign in with your SSO provider. Email links are turned off for this workspace.",
    ],
    [
      429,
      "A sign-in link was sent to this address a moment ago.",
      "A sign-in link was sent to this address a moment ago. Check your inbox, or wait a minute and ask again.",
    ],
    [
      400,
      "Disposable email addresses are not allowed.",
      "Disposable email addresses are not allowed.",
    ],
    [
      503,
      "Failed to send the sign-in email.",
      "Could not send the sign-in email. Try again in a moment.",
    ],
  ])(
    "a %i with %s shows the right message and keeps the form",
    async (status, detail, message) => {
      jest
        .spyOn(global, "fetch")
        .mockResolvedValue(jsonResponse(status, { detail }));

      render(<MagicLinkSignIn nextUrl={null} />);
      await requestLink("someone@example.com");

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(screen.queryByText("Check your email")).not.toBeInTheDocument();
      expect(screen.getByTestId("magic-link-email")).toBeInTheDocument();
    }
  );

  test("a network failure shows the send-failed message", async () => {
    jest.spyOn(global, "fetch").mockRejectedValue(new TypeError("offline"));

    render(<MagicLinkSignIn nextUrl={null} />);
    await requestLink("someone@example.com");

    await waitFor(() =>
      expect(
        screen.getByText(
          "Could not send the sign-in email. Try again in a moment."
        )
      ).toBeInTheDocument()
    );
  });
});
