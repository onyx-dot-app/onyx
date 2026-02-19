"use client";

import Logo from "@/refresh-components/Logo";
import IconButton from "@/refresh-components/buttons/IconButton";
import Chip from "@/refresh-components/Chip";
import { SvgGlobe, SvgExternalLink } from "@opal/icons";
import { cn } from "@/lib/utils";

interface SidePanelHeaderProps {
  tabReadingEnabled: boolean;
  currentTabUrl: string | null;
  onToggleTabReading: () => void;
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export default function SidePanelHeader({
  tabReadingEnabled,
  currentTabUrl,
  onToggleTabReading,
}: SidePanelHeaderProps) {
  const domain = currentTabUrl ? getDomain(currentTabUrl) : null;

  const handleOpenInOnyx = () => {
    window.open(`${window.location.origin}/app`, "_blank");
  };

  return (
    <header className="flex flex-col border-b border-border-01 bg-background">
      <div className="flex items-center justify-between px-4 py-3">
        <Logo />
        <div className="flex items-center gap-1">
          <IconButton
            icon={SvgGlobe}
            onClick={onToggleTabReading}
            tertiary
            tooltip={
              tabReadingEnabled ? "Stop reading this tab" : "Read this tab"
            }
            className={cn(
              tabReadingEnabled && "text-action-link-01 bg-background-tint-02"
            )}
          />
          <IconButton
            icon={SvgExternalLink}
            onClick={handleOpenInOnyx}
            tertiary
            tooltip="Open in Onyx"
          />
        </div>
      </div>
      {tabReadingEnabled && domain && (
        <div className="px-4 pb-2">
          <Chip icon={SvgGlobe}>{domain}</Chip>
        </div>
      )}
    </header>
  );
}
