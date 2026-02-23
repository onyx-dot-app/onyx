"use client";

import Logo from "@/refresh-components/Logo";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgEditBig, SvgExternalLink } from "@opal/icons";

interface SidePanelHeaderProps {
  onNewChat: () => void;
}

export default function SidePanelHeader({ onNewChat }: SidePanelHeaderProps) {
  const handleOpenInOnyx = () => {
    window.open(`${window.location.origin}/app`, "_blank");
  };

  return (
    <header className="flex items-center justify-between px-4 py-3 border-b border-border-01 bg-background">
      <Logo />
      <div className="flex items-center gap-1">
        <IconButton
          icon={SvgEditBig}
          onClick={onNewChat}
          tertiary
          tooltip="New chat"
        />
        <IconButton
          icon={SvgExternalLink}
          onClick={handleOpenInOnyx}
          tertiary
          tooltip="Open in Onyx"
        />
      </div>
    </header>
  );
}
