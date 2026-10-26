import { act, deferred, render, screen } from "@tests/setup/test-utils";
import OAuthPKCESupport from "@/sections/actions/oauth/OAuthPKCESupport";

const endpoints = {
  authorizationUrl: "https://provider.example/authorize",
  tokenUrl: "https://provider.example/token",
};

afterEach(() => jest.restoreAllMocks());

test("detects PKCE from endpoints without credentials", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify({ status: "supported" })));
  render(<OAuthPKCESupport {...endpoints} />);
  expect(
    await screen.findByText("Provider advertises S256 PKCE support.")
  ).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/oauth-config/pkce-support",
    expect.objectContaining({
      body: JSON.stringify({
        authorization_url: endpoints.authorizationUrl,
        token_url: endpoints.tokenUrl,
      }),
    })
  );
});

test("hides an obsolete result after endpoint edits", async () => {
  const response = deferred<Response>();
  jest.spyOn(global, "fetch").mockReturnValue(response.promise);
  const { rerender } = render(<OAuthPKCESupport {...endpoints} />);
  rerender(<OAuthPKCESupport {...endpoints} authorizationUrl="" />);
  await act(async () =>
    response.resolve(new Response(JSON.stringify({ status: "supported" })))
  );
  expect(
    screen.queryByText("Provider advertises S256 PKCE support.")
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("Enter valid HTTPS endpoints to check PKCE support.")
  ).toBeInTheDocument();
});
