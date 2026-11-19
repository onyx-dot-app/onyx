"use client";

import { useNavigation, usePathname, useSearchParams } from "@opal/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";

import { Button, Text } from "@opal/components";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  ConnectAppDecision,
  postConnectAppDecision,
} from "@/app/craft/services/externalAppsService";
import CometEdge from "@/refresh-components/CometEdge";
import { connectWithOAuth } from "@/lib/integrations/connect";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { startUserOAuth } from "@/lib/integrations/svc";
import { isSilentOAuthOutcome, oauthFailureDetail } from "@/lib/oauth/launch";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { CraftApp } from "@/lib/integrations/craft";
import IntegrationCredentialsModal from "@/sections/plugins/IntegrationCredentialsModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import { refreshSkillLists } from "@/lib/skills/cache";
import { locationKey } from "@/app/app/services/submitLocation";

interface SetupCardProps {
  // Correlation id for the parked `connect_app` request (from the packet).
  requestId: string;
  // Stable app ID the agent asked to connect.
  externalAppId: number;
  // The agent's one-line justification, when provided.
  reason: string | null;
  // The user-facing app row, when resolved — drives popup-vs-form + fields.
  userApp?: CraftApp;
}

/**
 * Connect-app card rendered from a `connect_app_request` packet. Finishing
 * "Connect" posts a "connected" decision (the parked agent tool resumes with
 * access). "Not now" posts "declined" (the agent gets a rejection and picks an
 * alternative).
 */
export default function SetupCard({
  requestId,
  externalAppId,
  reason,
  userApp,
}: SetupCardProps) {
  const t = useTranslations("craft.setupCard");
  const tActionPolicies = useTranslations("craft.actionPolicies");
  const navigation = useNavigation();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [credModalOpen, setCredModalOpen] = useState(false);
  const [decision, setDecision] = useState<ConnectAppDecision | null>(null);
  const { data: integrations } = useMemberIntegrations();

  const mountedRef = useRef(true);
  const resolvingRef = useRef(false);
  const autoResolvedRef = useRef(false);
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- tracks mount so async resolve skips updates after unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const appName =
    userApp?.name ?? t("appFallback.label", { id: externalAppId });
  const supportsOauth = userApp?.supports_oauth ?? false;
  const appLoading = userApp === undefined;
  const integration = integrations?.find(
    (candidate) => candidate.id === userApp?.integration_id
  );

  const resolve = useCallback(
    async (result: ConnectAppDecision) => {
      if (resolvingRef.current) return;
      resolvingRef.current = true;
      setBusy(true);
      setError(null);
      try {
        await postConnectAppDecision(requestId, result);
      } catch (e) {
        // POST failed (network error, or already resolved on another device).
        // Keep the card actionable so the user can retry.
        console.error("Failed to resolve connect-app request:", e);
        if (mountedRef.current) setError(t("error.generic"));
        return;
      } finally {
        resolvingRef.current = false;
        if (mountedRef.current) setBusy(false);
      }
      if (!mountedRef.current) return;
      setDecision(result);
      if (result === "connected") {
        void mutate(SWR_KEYS.integrations);
        void refreshSkillLists(mutate);
      }
    },
    [requestId, mutate, t]
  );

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- resolves the setup request on the server once the app reports it is connected
  useEffect(() => {
    if (!userApp?.authenticated || decision !== null || autoResolvedRef.current)
      return;
    autoResolvedRef.current = true;
    void resolve("connected");
  }, [userApp?.authenticated, decision, resolve]);

  async function connect() {
    setError(null);
    // Capabilities are unknown until the app row loads (the button is disabled).
    if (appLoading) return;
    if (!userApp) {
      setError(t("error.notConfigurable"));
      return;
    }
    if (userApp.authenticated) {
      await resolve("connected");
      return;
    }
    if (!supportsOauth) {
      if (!integration) {
        setError(t("error.notConfigurable"));
        return;
      }
      // Lock the actions so "Not now" can't decline while the form is open.
      setBusy(true);
      setCredModalOpen(true);
      return;
    }

    setBusy(true);
    try {
      const result = await connectWithOAuth(
        (path) => startUserOAuth(userApp.integration_id, path),
        locationKey(pathname, searchParams.toString())
      );
      if (!mountedRef.current) return;
      setBusy(false);
      if (result === "connected") await resolve("connected");
    } catch (e) {
      if (!mountedRef.current) return;
      setBusy(false);
      if (!isSilentOAuthOutcome(e))
        setError(
          oauthFailureDetail(e)?.description ??
            (e instanceof Error && e.message
              ? e.message
              : t("error.startFailed"))
        );
    }
  }

  const Logo = getAppTypeLogo(userApp?.app_type ?? "CUSTOM");

  // Stored credentials alone do not release the agent's pending request.
  const connected = decision === "connected";
  const decided = connected || decision === "declined";
  // Comet travels while pending (info), then settles to the outcome tone.
  const tone = decided ? (connected ? "success" : "error") : "info";

  if (decided) {
    return (
      <CometEdge active={false} settled tone={tone}>
        <div
          data-testid="setup-card"
          className={cn(
            "rounded-08 border bg-background-neutral-00 p-3 transition-colors",
            connected ? "border-status-success-03" : "border-status-error-03"
          )}
        >
          <Content
            font="secondary-body"
            icon={Logo}
            color={connected ? "default" : "error"}
            titleColor="text-03"
            title={
              connected
                ? t("connected.title", { app: appName })
                : t("skipped.title", { app: appName })
            }
          />
          {connected && (
            <Button
              prominence="tertiary"
              {...navigation.linkTo("/craft/v1/plugins")}
            >
              {tActionPolicies("title")}
            </Button>
          )}
        </div>
      </CometEdge>
    );
  }

  return (
    <CometEdge active settled={false} tone="info" speedSeconds={3.6}>
      <div
        data-testid="setup-card"
        className="rounded-08 border border-status-info-03 bg-background-neutral-00 p-3 flex flex-col gap-2"
      >
        <Content
          font="main-ui-action"
          icon={Logo}
          title={t("connect.title", { app: appName })}
          description={reason ?? t("reason.fallback", { app: appName })}
        />
        {error && (
          <Text font="secondary-body" color="text-03">
            {error}
          </Text>
        )}
        <div className="flex items-center justify-end gap-1">
          <Button
            prominence="secondary"
            size="sm"
            disabled={busy}
            onClick={() => void resolve("declined")}
          >
            {t("notNow.button")}
          </Button>
          <Button
            prominence="primary"
            size="sm"
            disabled={busy || appLoading}
            onClick={() => void connect()}
          >
            {busy
              ? t("waiting.button")
              : appLoading
                ? t("loading.button")
                : t("connect.title", { app: appName })}
          </Button>
        </div>
        {credModalOpen && integration && (
          <IntegrationCredentialsModal
            integration={integration}
            onClose={() => {
              setCredModalOpen(false);
              setBusy(false);
            }}
            onConnected={() => {
              setCredModalOpen(false);
              void resolve("connected");
            }}
          />
        )}
      </div>
    </CometEdge>
  );
}
