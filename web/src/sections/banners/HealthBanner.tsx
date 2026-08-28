"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { MessageCard, Text } from "@opal/components";

export default function HealthBanner() {
  const t = useTranslations("chat.banners");
  const { error } = useSWR(SWR_KEYS.health, errorHandlingFetcher);

  if (!error || error instanceof RedirectError) {
    return null;
  }

  const errorMessage = error instanceof Error ? error.message : String(error);

  return (
    <div className="z-banner fixed inset-0 bg-background-neutral-01/80">
      <div className="p-2">
        <MessageCard
          variant="error"
          title={t("healthBanner.backendUnavailable.title")}
          description={t("healthBanner.backendUnavailable.description")}
          bottomChildren={
            <div className="px-2">
              <Text>{errorMessage}</Text>
            </div>
          }
        />
      </div>
    </div>
  );
}
