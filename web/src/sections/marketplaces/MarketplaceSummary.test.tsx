import { render, screen } from "@tests/setup/test-utils";
import MarketplaceSummary from "@/sections/marketplaces/MarketplaceSummary";
import { marketplace } from "@/sections/marketplaces/__fixtures__/marketplace";

it("shows pending work separately from the last applied revision", () => {
  render(
    <MarketplaceSummary
      marketplace={{
        ...marketplace,
        sync_requested: false,
        sync_status: "applied",
        last_synced_revision: "old-commit",
        live_skill_count: 2,
        retired_skill_count: 1,
      }}
    />
  );
  expect(screen.getByText("Sync pending")).toBeInTheDocument();
  expect(screen.getByText("Applied revision: old-commit")).toBeInTheDocument();
  expect(screen.getByText("2 active skills · 1 retired")).toBeInTheDocument();
  expect(
    screen.getByText("GitHub · acme/tools · feature/tools")
  ).toBeInTheDocument();
  expect(screen.getByText("Folder: catalog")).toBeInTheDocument();
});

it("lets hosts hide unsupported kind counts and retains server errors", () => {
  render(
    <MarketplaceSummary
      countLabel={null}
      marketplace={{
        ...marketplace,
        sync_requested: false,
        sync_pending: false,
        sync_status: "failed",
        last_error: "Login is no longer active",
      }}
    />
  );
  expect(screen.queryByText(/active skills/)).not.toBeInTheDocument();
  expect(screen.getByText("Failed")).toBeInTheDocument();
  expect(screen.getByText("Login is no longer active")).toBeInTheDocument();
});
