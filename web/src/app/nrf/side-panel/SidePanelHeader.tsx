"use client";

import Logo from "@/refresh-components/Logo";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgEditBig, SvgExternalLink } from "@opal/icons";

interface SidePanelHeaderProps {
  onNewChat: () => void;
  chatSessionId?: string | null;
}

export default function SidePanelHeader({
  onNewChat,
  chatSessionId,
}: SidePanelHeaderProps) {
  const handleOpenInOnyx = () => {
    const path = chatSessionId ? `/app?chatId=${chatSessionId}` : "/app";
    window.open(`${window.location.origin}${path}`, "_blank");
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
