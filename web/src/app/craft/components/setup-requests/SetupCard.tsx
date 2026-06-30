"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { Button, Text } from "@opal/components";
import { Content } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  ConnectAppDecision,
  postConnectAppDecision,
  startExternalAppOAuth,
} from "@/app/craft/services/externalAppsService";
import CometEdge from "@/app/craft/components/CometEdge";
import {
  OAUTH_POPUP_MESSAGE_SOURCE,
  OAuthPopupMessage,
} from "@/app/craft/types/setupRequests";
import {
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import UserCredentialsModal from "@/app/craft/v1/apps/UserCredentialsModal";
import { SWR_KEYS } from "@/lib/swr-keys";

interface SetupCardProps {
  // Correlation id for the parked `connect_app` request (from the packet).
  requestId: string;
  // App slug the agent asked to connect; used as the label fallback.
  appSlug: string;
  // The agent's one-line justification, when provided.
  reason: string | null;
  // The user-facing app row, when resolved — drives popup-vs-form + fields.
  userApp?: ExternalAppUserResponse;
}

const POPUP_FEATURES = "popup,width=520,height=720";
const POPUP_POLL_MS = 600;

/**
 * Connect-app card rendered from a `connect_app_request` packet. "Connect" runs
 * the OAuth popup (or the credential form for token apps); finishing posts a
 * "connected" decision (→ the parked agent tool resumes with access), "Not now"
 * posts "declined" (→ the agent gets a rejection and picks an alternative).
 */
export default function SetupCard({
  requestId,
  appSlug,
  reason,
  userApp,
}: SetupCardProps) {
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [credModalOpen, setCredModalOpen] = useState(false);
  const [decision, setDecision] = useState<ConnectAppDecision | null>(null);

  const mountedRef = useRef(true);
  // Tears down the in-flight OAuth poll/listener; run on finish and on unmount.
  const cleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      cleanupRef.current?.();
    };
  }, []);

  const appName = userApp?.name ?? appSlug;
  const externalAppId = userApp?.id ?? null;
  const supportsOauth = userApp?.supports_oauth ?? false;
  const appLoading = userApp === undefined;

  async function resolve(result: ConnectAppDecision) {
    setError(null);
    try {
      await postConnectAppDecision(requestId, result);
    } catch (e) {
      // POST failed (network error, or already resolved on another device).
      // Keep the card actionable so the user can retry.
      console.error("Failed to resolve connect-app request:", e);
      if (mountedRef.current)
        setError("Something went wrong. Please try again.");
      return;
    }
    if (!mountedRef.current) return;
    setDecision(result);
    if (result === "connected") {
      void mutate(SWR_KEYS.buildExternalApps);
    }
  }

  async function confirmConnected(): Promise<boolean> {
    try {
      const apps = await mutate<ExternalAppUserResponse[]>(
        SWR_KEYS.buildExternalApps
      );
      return !!apps?.some(
        (app) => app.id === externalAppId && app.authenticated
      );
    } catch {
      return false;
    }
  }

  function awaitOAuthCompletion(popup: Window) {
    let settled = false;

    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data as Partial<OAuthPopupMessage> | undefined;
      if (data?.source !== OAUTH_POPUP_MESSAGE_SOURCE) return;
      if (data.externalAppId !== externalAppId) return;
      finish(true);
    }

    // Close alone isn't a cancel: the success postMessage can lose the race with
    // this poll, so confirm against the server before giving up.
    async function onClose() {
      if (settled) return;
      clearInterval(poll);
      finish(await confirmConnected());
    }

    const poll = setInterval(() => {
      if (popup.closed) void onClose();
    }, POPUP_POLL_MS);
    window.addEventListener("message", onMessage);

    const teardown = () => {
      window.removeEventListener("message", onMessage);
      clearInterval(poll);
    };
    cleanupRef.current = teardown;

    function finish(connected: boolean) {
      if (settled) return;
      settled = true;
      teardown();
      cleanupRef.current = null;
      if (mountedRef.current) setBusy(false);
      // Unconfirmed attempts leave the card live to retry rather than decline.
      if (connected) void resolve("connected");
    }
  }

  async function connect() {
    setError(null);
    // Capabilities are unknown until the app row loads (the button is disabled).
    if (appLoading) return;
    if (externalAppId === null) {
      setError("This app can't be set up from here.");
      return;
    }
    if (!supportsOauth) {
      // Lock the actions so "Not now" can't decline while the form is open.
      setBusy(true);
      setCredModalOpen(true);
      return;
    }

    setBusy(true);
    try {
      const { authorize_url } = await startExternalAppOAuth(externalAppId);
      const popup = window.open(authorize_url, "_blank", POPUP_FEATURES);
      if (!popup) {
        setBusy(false);
        setError(
          "Couldn't open the setup window — allow popups and try again."
        );
        return;
      }
      awaitOAuthCompletion(popup);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : "Failed to start setup");
    }
  }

  const Logo = getAppTypeLogo(userApp?.app_type ?? "CUSTOM");

  // `decision` is this session's click; `userApp.authenticated` is the durable
  // truth, so a connected card stays connected after navigating away and back.
  const connected =
    decision === "connected" || (userApp?.authenticated ?? false);
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
            sizePreset="secondary"
            variant="body"
            icon={Logo}
            color={connected ? "muted" : "danger"}
            title={
              connected
                ? `${appName} connected.`
                : `Skipped connecting ${appName}.`
            }
          />
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
          sizePreset="main-ui"
          variant="section"
          icon={Logo}
          title={`Connect ${appName}`}
          description={
            reason ?? `The agent needs ${appName} to continue this task.`
          }
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
            Not now
          </Button>
          <Button
            prominence="primary"
            size="sm"
            disabled={busy || appLoading}
            onClick={() => void connect()}
          >
            {busy ? "Waiting…" : appLoading ? "Loading…" : `Connect ${appName}`}
          </Button>
        </div>
        {userApp && (
          <UserCredentialsModal
            open={credModalOpen}
            onClose={() => {
              setCredModalOpen(false);
              setBusy(false);
            }}
            onSaved={() => void resolve("connected")}
            userApp={userApp}
          />
        )}
      </div>
    </CometEdge>
  );
}
