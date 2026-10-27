"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import type { ProviderEntry } from "@/lib/languageModels/types";

/** A provider's names as the UI shows them. */
export interface ProviderNames {
  productName: string;
  companyName: string;
}

/**
 * Resolves a provider entry's names for display: brand names as they are, and
 * the translated copy for a provider whose names are copy (`copyKey`).
 */
export function useProviderNames(): (
  entry: Pick<ProviderEntry, "productName" | "companyName" | "copyKey">
) => ProviderNames {
  const t = useTranslations("admin.languageModels.providers");
  return useCallback(
    (entry) =>
      entry.copyKey
        ? {
            productName: t(`${entry.copyKey}.productName`),
            companyName: t(`${entry.copyKey}.companyName`),
          }
        : { productName: entry.productName, companyName: entry.companyName },
    [t]
  );
}
