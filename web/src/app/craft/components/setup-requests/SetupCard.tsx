"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { Button, Text } from "@opal/components";
import {
  ConnectAppDecision,
  postConnectAppDecision,
  startExternalAppOAuth,
} from "@/app/craft/services/externalAppsService";
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
// On popup close, wait briefly for an in-flight success message before treating
// the close as a cancel — the two arrive on unordered task queues.
const POPUP_CLOSE_GRACE_MS = 500;

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
  // The app row drives the popup-vs-form choice; until it resolves we can't
  // tell, so the action stays disabled rather than routing the wrong branch.
  const appLoading = userApp === undefined;

  async function resolve(result: ConnectAppDecision) {
    setDecision(result);
    try {
      await postConnectAppDecision(requestId, result);
    } catch (e) {
      // Already resolved (timed out, other device) — leave the terminal state.
      console.error("Failed to resolve connect-app request:", e);
    }
    if (result === "connected") {
      void mutate(SWR_KEYS.buildExternalApps);
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

    const poll = setInterval(() => {
      if (!popup.closed) return;
      clearInterval(poll);
      // The popup may have just posted its success message; give it a beat to
      // land before declaring a cancel. finish() is idempotent, so a message
      // arriving first still wins.
      setTimeout(() => finish(false), POPUP_CLOSE_GRACE_MS);
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
      // A closed popup without a success message is just a cancelled attempt —
      // leave the card live so the user can retry rather than declining.
      if (connected) void resolve("connected");
    }
  }

  async function connect() {
    setError(null);
    if (externalAppId === null) {
      setError("This app can't be set up from here.");
      return;
    }
    if (!supportsOauth) {
      if (userApp) {
        // Hold both actions while the credential modal is open so a stray
        // "Not now" can't decline the request the form is about to connect.
        setBusy(true);
        setCredModalOpen(true);
      } else {
        setError("This app needs setup on the Apps page.");
      }
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

  if (decision !== null) {
    return (
      <div
        data-testid="setup-card"
        className="rounded-08 border border-border-02 bg-background-neutral-00 p-3 flex items-center gap-2"
      >
        <Logo className="size-5 shrink-0" />
        <Text font="secondary-body" color="text-03">
          {decision === "connected"
            ? `${appName} connected.`
            : `Skipped connecting ${appName}.`}
        </Text>
      </div>
    );
  }

  return (
    <div
      data-testid="setup-card"
      className="rounded-08 border border-status-info-03 bg-background-neutral-00 p-3 flex flex-col gap-2"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Logo className="size-5 shrink-0" />
        <Text font="main-ui-action" color="text-05" nowrap>
          {`Connect ${appName}`}
        </Text>
      </div>
      <Text font="secondary-body" color="text-03">
        {reason ?? `The agent needs ${appName} to continue this task.`}
      </Text>
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
  );
}
