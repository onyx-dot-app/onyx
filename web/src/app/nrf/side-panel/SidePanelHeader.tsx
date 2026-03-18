"use client";

import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";
import Logo from "@/refresh-components/Logo";
import { Button } from "@opal/components";
import { SvgEditBig, SvgExternalLink } from "@opal/icons";

interface SidePanelHeaderProps {
  onNewChat: () => void;
  chatSessionId?: string | null;
}

export default function SidePanelHeader({
  onNewChat,
  chatSessionId,
}: SidePanelHeaderProps) {
  const handleOpenInApp = () => {
    const path = chatSessionId ? `/app?chatId=${chatSessionId}` : "/app";
    window.open(`${window.location.origin}${path}`, "_blank");
  };

  return (
    <header className="flex items-center justify-between px-4 py-3 border-b border-border-01 bg-background">
      <Logo />
      <div className="flex items-center gap-1">
        <Button
          prominence="tertiary"
          icon={SvgEditBig}
          onClick={onNewChat}
          tooltip="Nuevo chat"
        />
        <Button
          prominence="tertiary"
          icon={SvgExternalLink}
          onClick={handleOpenInApp}
          tooltip={`Abrir en ${DEFAULT_APPLICATION_NAME}`}
        />
      </div>
    </header>
  );
}
