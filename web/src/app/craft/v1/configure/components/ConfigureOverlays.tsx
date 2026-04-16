"use client";

import { cn } from "@/lib/utils";
import { Button, MessageCard } from "@opal/components";

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
      <MessageCard
        variant="info"
        title="Existing sessions won't have access to this data"
        description="Once synced, documents from this connector will be available in your new sessions!"
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
        "fixed bottom-16 left-1/2 -translate-x-1/2 z-toast transition-all duration-300 ease-in-out",
        visible
          ? "opacity-100 translate-y-0"
          : "opacity-0 translate-y-4 pointer-events-none"
      )}
    >
      <MessageCard
        variant="warning"
        title={
          isUpdating ? "Updating..." : "Click Update to apply your changes"
        }
        description="Your sandbox will be recreated with your new settings. Previously running sessions will not be affected by your changes."
        rightChildren={
          !isUpdating ? <Button onClick={onUpdate}>Update</Button> : undefined
        }
      />
    </div>
  );
}
