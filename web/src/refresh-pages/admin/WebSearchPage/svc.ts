import { CONTENT_PROVIDER_DETAILS } from "@/refresh-pages/admin/WebSearchPage/contentProviderUtils";
import type { WebContentProviderView } from "@/refresh-pages/admin/WebSearchPage/interfaces";

async function parseErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  try {
    const body = await res.json();
    return body?.detail ?? fallback;
  } catch {
    return fallback;
  }
}

export async function activateSearchProvider(
  providerId: number
): Promise<void> {
  const res = await fetch(
    `/api/admin/web-search/search-providers/${providerId}/activate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to set provider as default.")
    );
  }
}

export async function deactivateSearchProvider(
  providerId: number
): Promise<void> {
  const res = await fetch(
    `/api/admin/web-search/search-providers/${providerId}/deactivate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to deactivate provider.")
    );
  }
}

export async function activateContentProvider(
  provider: WebContentProviderView
): Promise<void> {
  if (provider.provider_type === "onyx_web_crawler") {
    const res = await fetch(
      "/api/admin/web-search/content-providers/reset-default",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }
    );
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  } else if (provider.id > 0) {
    const res = await fetch(
      `/api/admin/web-search/content-providers/${provider.id}/activate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }
    );
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  } else {
    const payload = {
      id: null,
      name:
        provider.name ||
        CONTENT_PROVIDER_DETAILS[provider.provider_type]?.label ||
        provider.provider_type,
      provider_type: provider.provider_type,
      api_key: null,
      api_key_changed: false,
      config: provider.config ?? null,
      activate: true,
    };

    const res = await fetch("/api/admin/web-search/content-providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(
        await parseErrorDetail(res, "Failed to set crawler as default.")
      );
    }
  }
}

export async function deactivateContentProvider(
  providerId: number,
  providerType: string
): Promise<void> {
  const endpoint =
    providerType === "onyx_web_crawler" || providerId < 0
      ? "/api/admin/web-search/content-providers/reset-default"
      : `/api/admin/web-search/content-providers/${providerId}/deactivate`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to deactivate provider.")
    );
  }
}

export async function disconnectProvider(
  id: number,
  category: "search" | "content",
  replacementProviderId: string | null
): Promise<void> {
  // If a replacement was selected (not "No Default"), activate it first
  if (replacementProviderId && replacementProviderId !== "__none__") {
    const repId = Number(replacementProviderId);
    const activateEndpoint =
      category === "search"
        ? `/api/admin/web-search/search-providers/${repId}/activate`
        : `/api/admin/web-search/content-providers/${repId}/activate`;
    const activateRes = await fetch(activateEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!activateRes.ok) {
      throw new Error(
        await parseErrorDetail(
          activateRes,
          "Failed to activate replacement provider."
        )
      );
    }
  }

  const res = await fetch(`/api/admin/web-search/${category}-providers/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to disconnect provider.")
    );
  }
}
