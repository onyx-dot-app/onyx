"use client";

import { cn } from "@/lib/utils";
import Message from "@/refresh-components/messages/Message";

interface ConnectorInfoOverlayProps {
  visible: boolean;
}

export function ConnectorInfoOverlay({ visible }: ConnectorInfoOverlayProps) {
  return (
    <div
      className={cn(
        "fixed bottom-16 left-1/2 -translate-x-1/2 z-toast transition-all duration-300 ease-in-out",
        visible
          ? "opacity-100 translate-y-0"
          : "opacity-0 translate-y-4 pointer-events-none"
      )}
    >
      <Message
        info
        text="Existing sessions won't have access to this data"
        description="Once synced, documents from this connector will be available in your new sessions!"
        close={false}
      />
    </div>
  );
}

interface ReprovisionWarningOverlayProps {
  visible: boolean;
  onUpdate?: () => void;
  isUpdating?: boolean;
}

export function ReprovisionWarningOverlay({
  visible,
  onUpdate,
  isUpdating,
}: ReprovisionWarningOverlayProps) {
  return (
    <div
      className={cn(
        "transition-all duration-300 ease-in-out",
        visible
          ? "opacity-100 translate-y-0"
          : "opacity-0 translate-y-4 pointer-events-none"
      )}
    >
      <Message
        warning
        text={isUpdating ? "Updating..." : "Click Update to apply your changes"}
        description="Your sandbox will be recreated with your new settings. Previously running sessions will not be affected by your changes."
        close={false}
        actions={isUpdating ? false : "Update"}
        onAction={isUpdating ? undefined : onUpdate}
      />
    </div>
  );
}
