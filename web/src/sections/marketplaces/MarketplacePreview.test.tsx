import { render, screen } from "@tests/setup/test-utils";
import MarketplacePreview from "@/sections/marketplaces/MarketplacePreview";

it("shows each validated entry outcome and its reason", () => {
  render(
    <MarketplacePreview
      preview={{
        status: "complete",
        revision: "commit-one",
        entries: [
          {
            status: "ok",
            entry_key: "team/alpha",
            name: "alpha",
            description: "First skill",
            path: "skills/alpha",
          },
          {
            status: "blocked",
            entry_key: "team/beta",
            reason: "Name already taken",
            path: "skills/beta",
          },
          {
            status: "not_supported",
            entry_key: "remote",
            reason: "Remote sources are unsupported",
          },
        ],
      }}
    />
  );
  for (const text of [
    "Ready",
    "Blocked",
    "Not supported",
    "First skill",
    "Name already taken",
    "Remote sources are unsupported",
    "skills/alpha",
    "commit-one",
  ]) {
    expect(screen.getByText(text)).toBeInTheDocument();
  }
});

it("offers a copyable sample for a missing catalog", () => {
  render(
    <MarketplacePreview
      preview={{
        status: "failed",
        revision: "commit-one",
        reason: "Cannot read marketplace: Marketplace manifest is missing",
      }}
    />
  );
  expect(
    screen.getByRole("button", { name: "Copy sample" })
  ).toBeInTheDocument();
  expect(screen.getByText(/Save this as/)).toHaveTextContent(
    ".claude-plugin/marketplace.json"
  );
  expect(screen.getByText(/"plugins"/)).toHaveTextContent(
    '"source": "./team-skills"'
  );
});
