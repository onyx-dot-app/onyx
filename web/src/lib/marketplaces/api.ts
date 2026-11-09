import * as yup from "yup";
import { errorHandlingFetchWith, errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  marketplaceDetailSchema,
  marketplacePreviewSchema,
  marketplaceSchema,
  type MarketplaceAccessUpdate,
  type MarketplaceCreate,
  type MarketplaceSource,
  type RetirementConfirmation,
} from "@/lib/marketplaces/types";

const jsonHeaders = { "Content-Type": "application/json" };
const strict = { strict: true };

export async function listMarketplaces() {
  const data = await errorHandlingFetcher<unknown>(SWR_KEYS.marketplaces);
  return yup.array(marketplaceSchema).defined().validateSync(data, strict);
}

export async function getMarketplace(id: string) {
  const data = await errorHandlingFetcher<unknown>(SWR_KEYS.marketplace(id));
  return marketplaceDetailSchema.validateSync(data, strict);
}

export async function previewMarketplace(source: MarketplaceSource) {
  const data = await errorHandlingFetchWith<unknown>(
    `${SWR_KEYS.marketplaces}/preview`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(source),
    }
  );
  return marketplacePreviewSchema.validateSync(data, strict);
}

export async function createMarketplace(source: MarketplaceCreate) {
  const data = await errorHandlingFetchWith<unknown>(SWR_KEYS.marketplaces, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(source),
  });
  return marketplaceSchema.validateSync(data, strict);
}

export async function requestMarketplaceSync(id: string) {
  const data = await errorHandlingFetchWith<unknown>(
    `${SWR_KEYS.marketplace(id)}/sync`,
    { method: "POST" }
  );
  return marketplaceSchema.validateSync(data, strict);
}

export async function replaceMarketplaceLogin(id: string) {
  const data = await errorHandlingFetchWith<unknown>(
    `${SWR_KEYS.marketplace(id)}/replace-login`,
    { method: "POST" }
  );
  return marketplaceSchema.validateSync(data, strict);
}

export async function confirmMarketplaceRetirements({
  id,
  confirmation,
}: {
  id: string;
  confirmation: RetirementConfirmation;
}) {
  const data = await errorHandlingFetchWith<unknown>(
    `${SWR_KEYS.marketplace(id)}/confirm-retirements`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        revision: confirmation.revision,
        skill_ids: confirmation.skill_ids,
      }),
    }
  );
  return marketplaceSchema.validateSync(data, strict);
}

export async function updateMarketplaceAccess({
  id,
  access,
}: {
  id: string;
  access: MarketplaceAccessUpdate;
}) {
  const data = await errorHandlingFetchWith<unknown>(
    `${SWR_KEYS.marketplace(id)}/access`,
    { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(access) }
  );
  return marketplaceSchema.validateSync(data, strict);
}

export async function removeMarketplace(id: string): Promise<void> {
  await errorHandlingFetchWith<unknown>(SWR_KEYS.marketplace(id), {
    method: "DELETE",
  });
}
