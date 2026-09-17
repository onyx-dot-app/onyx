"use client";

import { useCallback, useState } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import { SvgExternalLink, SvgLink, SvgUnplug } from "@opal/icons";
import { Card } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import Title from "@/components/ui/title";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { LtiCourseConnectorStatus } from "@/refresh-pages/tutor/CanvasCourseSetupView";
import {
  attachCanvasCredentialToCourse,
  CanvasOAuthCancelledError,
  disconnectCanvasOAuth,
  startCanvasOAuth,
} from "@/refresh-pages/tutor/canvasOAuth";

interface TutorInstructorCanvasConnectionProps {
  courseId: string;
  onConnectionChanged?: () => void | Promise<void>;
}

function connectionSummary(status: LtiCourseConnectorStatus): {
  title: string;
  description: string;
  tone: "ok" | "warning" | "neutral";
} {
  const setup = status.setup;
  const canvasUser = setup?.connected_canvas_user;
  switch (setup?.connection_state) {
    case "connected":
      return {
        tone: "ok",
        title: "Canvas connected",
        description: canvasUser
          ? `Syncing as ${canvasUser}. Access renews automatically.`
          : "Access renews automatically.",
      };
    case "expired":
      return {
        tone: "warning",
        title: "Canvas connection expired",
        description:
          "Canvas no longer accepts this authorization (it was revoked or the account changed). Reconnect to resume syncing.",
      };
    case "static_token":
      return {
        tone: "neutral",
        title: "Connected with a pasted access token",
        description: setup?.oauth_available
          ? "This course uses a manually generated Canvas token. Reconnect to switch to Canvas sign-in, which renews automatically."
          : "This course uses a manually generated Canvas token. If it is revoked in Canvas, syncing will stop.",
      };
    default:
      return {
        tone: "neutral",
        title: "Canvas connection",
        description: "Connection details are unavailable.",
      };
  }
}

export default function TutorInstructorCanvasConnection({
  courseId,
  onConnectionChanged,
}: TutorInstructorCanvasConnectionProps) {
  const statusKey = `/api/auth/lti/course/${encodeURIComponent(
    courseId
  )}/connector-status`;
  const { data: status, mutate } = useSWR<LtiCourseConnectorStatus>(
    statusKey,
    errorHandlingFetcher,
    { refreshInterval: 30_000 }
  );
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);

  const notifyChanged = useCallback(async () => {
    await mutate();
    await onConnectionChanged?.();
  }, [mutate, onConnectionChanged]);

  const handleReconnect = useCallback(async () => {
    setIsReconnecting(true);
    try {
      const credentialId = await startCanvasOAuth(courseId);
      await attachCanvasCredentialToCourse(courseId, credentialId);
      toast.success("Canvas reconnected. A full sync will start shortly.");
      await notifyChanged();
    } catch (e) {
      if (e instanceof CanvasOAuthCancelledError) {
        toast.info(e.message);
      } else {
        toast.error(
          e instanceof Error ? e.message : "Could not reconnect Canvas."
        );
      }
    } finally {
      setIsReconnecting(false);
    }
  }, [courseId, notifyChanged]);

  const handleDisconnect = useCallback(async () => {
    if (
      !window.confirm(
        "Disconnect Canvas? Syncing pauses until an instructor reconnects. Already indexed content stays available."
      )
    ) {
      return;
    }
    setIsDisconnecting(true);
    try {
      await disconnectCanvasOAuth(courseId);
      toast.success("Canvas disconnected.");
      await notifyChanged();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Could not disconnect Canvas."
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [courseId, notifyChanged]);

  if (!status?.setup || !status.has_connector) {
    return null;
  }

  const summary = connectionSummary(status);
  const oauthAvailable = status.setup.oauth_available;
  const connectionState = status.setup.connection_state;
  const canDisconnect = connectionState === "connected";
  const reconnectLabel =
    connectionState === "connected" ? "Reauthorize" : "Reconnect Canvas";

  return (
    <>
      <Title className="mb-2 mt-8" size="md">
        Canvas connection
      </Title>
      {connectionState === "expired" && (
        <div className="mb-3">
          <Callout type="warning" title="Syncing is paused">
            Reconnect Canvas so new course content keeps flowing to the tutor.
            Any instructor of this course can do this.
          </Callout>
        </div>
      )}
      <Card className="flex flex-col gap-4 px-6 py-5 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-1">
          <Text as="p" mainUiAction text05>
            {summary.title}
          </Text>
          <Text as="p" secondaryBody text03>
            {summary.description}
          </Text>
        </div>
        {oauthAvailable && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              prominence={
                connectionState === "connected" ? "secondary" : "primary"
              }
              icon={connectionState === "connected" ? SvgLink : SvgExternalLink}
              disabled={isReconnecting || isDisconnecting}
              onClick={() => void handleReconnect()}
            >
              {isReconnecting ? "Waiting for Canvas" : reconnectLabel}
            </Button>
            {canDisconnect && (
              <Button
                prominence="tertiary"
                icon={SvgUnplug}
                disabled={isReconnecting || isDisconnecting}
                onClick={() => void handleDisconnect()}
              >
                Disconnect
              </Button>
            )}
          </div>
        )}
      </Card>
    </>
  );
}
