"use client";

import { useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { errorHandlingFetcher, RedirectError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { MessageCard, Text } from "@opal/components";
import { useSettings } from "@/lib/settings/hooks";

export default function HealthBanner() {
  const t = useTranslations("chat.banners");
  const { appName } = useSettings();
  // one failed health check is not an outage. iOS Safari aborts
  // in-flight fetches when a file download starts ("Load failed"), so the
  // overlay waits for a second consecutive failure once the backend has
  // answered at least once.
  const [failures, setFailures] = useState(0);
  const { data, error } = useSWR(SWR_KEYS.health, errorHandlingFetcher, {
    onSuccess: () => {
      setFailures(0);
    },
    onError: () => {
      setFailures((n) => n + 1);
    },
  });

  if (!error || error instanceof RedirectError) {
    return null;
  }
  if (data !== undefined && failures < 2) {
    return null;
  }

  const errorMessage = error instanceof Error ? error.message : String(error);

  return (
    <div className="z-banner fixed inset-0 bg-background-neutral-01/80">
      <div className="p-2">
        <MessageCard
          variant="error"
          title={t("healthBanner.backendUnavailable.title")}
          description={t("healthBanner.backendUnavailable.description", {
            appName,
          })}
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
