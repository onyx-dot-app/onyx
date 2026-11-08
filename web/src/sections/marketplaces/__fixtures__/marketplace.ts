import type {
  Marketplace,
  MarketplaceDetail,
  MarketplacePreview,
} from "@/lib/marketplaces/types";

export const marketplace: Marketplace = {
  id: "10000000-0000-4000-8000-000000000001",
  name: "Team tools",
  provider: "github",
  provider_config: {
    owner: "acme",
    repo: "tools",
    ref: "feature/tools",
    folder: "catalog",
  },
  owner_user_id: "20000000-0000-4000-8000-000000000002",
  login_user_id: null,
  public_permission: null,
  installation_policy: "AVAILABLE",
  group_shares: [],
  sync_requested: true,
  sync_pending: true,
  sync_status: null,
  last_synced_revision: null,
  last_synced_at: null,
  last_error: null,
  blocked_entries: {},
  retirement_proposal: null,
  live_skill_count: 0,
  retired_skill_count: 0,
};
export const detail: MarketplaceDetail = {
  marketplace,
  skills: [
    {
      id: "30000000-0000-4000-8000-000000000003",
      name: "alpha",
      current_version_id: null,
      retired_at: null,
      follows_marketplace_access: true,
    },
  ],
};
export const preview: MarketplacePreview = {
  status: "complete",
  revision: "commit-a",
  entries: [
    {
      status: "ok",
      entry_key: "team/alpha",
      name: "alpha",
      path: "skills/alpha",
      description: "First skill",
    },
  ],
};
