"use client";

import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { useNavigation } from "@opal/navigation";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useUser } from "@/providers/UserProvider";

/** Uses the existing Apps connection flow and rechecks its shared SWR cache. */
export default function GitHubConnection() {
  const t = useTranslations("marketplaces.githubConnection");
  const common = useTranslations("marketplaces");
  const navigation = useNavigation();
  const { isAdmin } = useUser();
  const { data, error } = useUserExternalApps();
  const { mutate } = useSWRConfig();
  const github = data?.find((app) => app.app_type === "GITHUB");
  const message = github?.authenticated
    ? t("connected")
    : github
      ? t("connect")
      : data
        ? isAdmin
          ? t("setUp")
          : t("askAdmin")
        : t("needsConnection");
  return (
    <MessageCard
      outerPadding={1}
      innerPadding={1}
      variant={error ? "error" : "info"}
      title={error ? common("connectionError") : message}
      rightChildren={
        <Button
          prominence="tertiary"
          onClick={() => void mutate(SWR_KEYS.buildExternalApps)}
        >
          {common("retry")}
        </Button>
      }
      bottomChildren={
        !github?.authenticated && (github || (data && isAdmin)) ? (
          <Button
            prominence="secondary"
            {...navigation.linkTo(
              github ? "/craft/v1/apps" : "/admin/craft/apps"
            )}
          >
            {github ? t("connectButton.label") : t("setUpButton.label")}
          </Button>
        ) : undefined
      }
    />
  );
}
