import type {
  MarketplaceDetail,
  MarketplacePreview,
  MarketplaceSummary,
} from "@/lib/marketplaces/types";

export const MARKETPLACE_ID = "22222222-2222-4222-8222-222222222222";

export function summaryFixture(
  over: Partial<MarketplaceSummary> = {}
): MarketplaceSummary {
  return {
    id: MARKETPLACE_ID,
    name: "acme/plugins",
    scope: "personal",
    repository: "acme/plugins",
    folder: null,
    ref: null,
    default_installation_policy: null,
    can_manage: true,
    login_user: { id: "user-1", email: "me@example.com" },
    plugin_count: 2,
    last_synced_at: "2026-11-01T10:00:00Z",
    last_synced_revision: "a".repeat(40),
    last_error: null,
    syncing: false,
    created_at: "2026-10-01T10:00:00Z",
    ...over,
  };
}

export function detailFixture(
  over: Partial<MarketplaceDetail> = {}
): MarketplaceDetail {
  return {
    ...summaryFixture(),
    login_has_github: true,
    entries: [
      {
        key: "review-kit",
        path: "plugins/review-kit",
        status: "ok",
        reason: null,
        reason_code: null,
        plugin_id: "33333333-3333-4333-8333-333333333333",
      },
      {
        key: "plan-kit",
        path: "plugins/plan-kit",
        status: "ok",
        reason: null,
        reason_code: null,
        plugin_id: "44444444-4444-4444-8444-444444444444",
      },
      {
        key: "npm-kit",
        path: null,
        status: "not_supported",
        reason: "Not supported in Onyx",
        reason_code: null,
        plugin_id: null,
      },
    ],
    plugins: [
      { id: "44444444-4444-4444-8444-444444444444", name: "plan-kit" },
      { id: "33333333-3333-4333-8333-333333333333", name: "review-kit" },
    ],
    ...over,
  };
}

export function previewFixture(
  over: Partial<MarketplacePreview> = {}
): MarketplacePreview {
  return {
    repository: "acme/plugins",
    folder: "catalog",
    ref: "main",
    revision: "b".repeat(40),
    status: "complete",
    name: "acme-plugins",
    reason: null,
    added_personal: false,
    added_company: false,
    entries: [
      {
        key: "review-kit",
        path: "plugins/review-kit",
        status: "ok",
        reason: null,
        reason_code: null,
        description: "Review pull requests.",
        version: "1.2.0",
        skills: [
          { name: "review", description: "Review." },
          { name: "summarize", description: "Summarize." },
        ],
        needs: [
          {
            kind: "mcp",
            name: "linear",
            url: "https://mcp.linear.app/mcp",
            transport: "http",
            supported: true,
            state: "not_added",
            integration_id: null,
            url_problem: null,
          },
        ],
        warnings: [],
      },
      {
        key: "broken-kit",
        path: "plugins/broken-kit",
        status: "blocked",
        reason: "The plugin has no skills.",
        reason_code: null,
        description: null,
        version: null,
        skills: [],
        needs: [],
        warnings: [],
      },
    ],
    ...over,
  };
}
