import type { Page, Route } from "@playwright/test";
import type {
  MarketplaceCreateRequest,
  MarketplaceDetail,
  MarketplacePreview,
  MarketplaceSource,
} from "@/lib/marketplaces/types";

/** The backend reads GitHub through module constants and an SSRF guard that
 * refuses loopback hosts, so a running server cannot reach a local fake
 * GitHub. */
export class FakeMarketplacesApi {
  readonly marketplaces = new Map<string, MarketplaceDetail>();
  readonly syncRequests: string[] = [];
  private revision = 1;

  static async install(page: Page): Promise<FakeMarketplacesApi> {
    const api = new FakeMarketplacesApi();
    await page.route("**/api/marketplaces**", (route) => api.handle(route));
    return api;
  }

  preview(source: MarketplaceSource): MarketplacePreview {
    return {
      repository: source.repository,
      folder: source.folder,
      ref: source.ref,
      revision: this.sha(),
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
          skills: [{ name: "review", description: "Review a change." }],
          needs: [],
          warnings: [],
        },
        {
          key: "npm-kit",
          path: null,
          status: "not_supported",
          reason: "Onyx cannot install a plugin from a 'npm' source.",
          reason_code: null,
          description: null,
          version: null,
          skills: [],
          needs: [],
          warnings: [],
        },
      ],
    };
  }

  private sha(): string {
    return String(this.revision).padStart(40, "0");
  }

  private created(request: MarketplaceCreateRequest): MarketplaceDetail {
    const now = new Date().toISOString();
    const plugin_id = crypto.randomUUID();
    return {
      id: crypto.randomUUID(),
      name: request.repository,
      scope: request.scope,
      repository: request.repository,
      folder: request.folder,
      ref: request.ref,
      default_installation_policy:
        request.scope === "company"
          ? (request.default_installation_policy ?? "AVAILABLE")
          : null,
      can_manage: true,
      login_has_github: true,
      login_user: { id: crypto.randomUUID(), email: "admin_user@example.com" },
      plugin_count: 1,
      last_synced_at: now,
      last_synced_revision: this.sha(),
      last_error: null,
      syncing: false,
      created_at: now,
      entries: [
        {
          key: "review-kit",
          path: "plugins/review-kit",
          status: "ok",
          reason: null,
          reason_code: null,
          plugin_id,
        },
      ],
      plugins: [{ id: plugin_id, name: "review-kit" }],
    };
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(
      /^\/api\/marketplaces/,
      ""
    );
    const method = request.method();
    if (method === "POST" && path === "/preview") {
      const source: MarketplaceSource = request.postDataJSON();
      return route.fulfill({ json: this.preview(source) });
    }
    if (method === "POST" && path === "") {
      const detail = this.created(request.postDataJSON());
      this.marketplaces.set(detail.id, detail);
      return route.fulfill({ json: detail });
    }
    if (method === "GET" && path === "") {
      return route.fulfill({
        json: { marketplaces: Array.from(this.marketplaces.values()) },
      });
    }
    const match = /^\/([^/]+)(\/sync)?$/.exec(path);
    const detail = match?.[1] ? this.marketplaces.get(match[1]) : undefined;
    if (!detail)
      return route.fulfill({ status: 404, json: { detail: "Not found." } });
    if (method === "POST" && match?.[2]) {
      this.syncRequests.push(detail.id);
      this.revision += 1;
      const synced: MarketplaceDetail = {
        ...detail,
        last_synced_at: new Date().toISOString(),
        last_synced_revision: this.sha(),
        plugin_count: detail.plugin_count + 1,
      };
      this.marketplaces.set(detail.id, synced);
      return route.fulfill({ json: { ...synced, syncing: true } });
    }
    return route.fulfill({ json: detail });
  }
}
