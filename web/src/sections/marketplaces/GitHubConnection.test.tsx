import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import GitHubConnection from "@/sections/marketplaces/GitHubConnection";

it("uses the existing Apps connection flow and refreshes connection state", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      new Response(
        JSON.stringify([{ app_type: "GITHUB", authenticated: false }])
      )
    );
  const user = setupUser();
  render(<GitHubConnection />);
  expect(
    await screen.findByRole("link", { name: /connect github/i })
  ).toHaveAttribute("href", "/craft/v1/apps");
  fetchSpy.mockResolvedValue(
    new Response(JSON.stringify([{ app_type: "GITHUB", authenticated: true }]))
  );
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("link", { name: /connect github/i })
    ).not.toBeInTheDocument()
  );
  fetchSpy.mockRestore();
});
