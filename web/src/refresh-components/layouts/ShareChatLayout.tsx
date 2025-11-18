"use client";

import { useEffect, useState } from "react";
import { ChatSession } from "@/app/chat/interfaces";
import {
  useHeaderActions,
  useHeaderActionsValue,
} from "@/refresh-components/contexts/HeaderActionsContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgShare from "@/icons/share";
import ShareChatSessionModal from "@/app/chat/components/modal/ShareChatSessionModal";
import { cn } from "@/lib/utils";
import Button from "../buttons/Button";

export interface ShareChatLayoutProps {
  chatSession: ChatSession | null;
  children: React.ReactNode;
  reserveHeaderSpace?: boolean;
}

export default function ShareChatLayout({
  chatSession,
  children,
  reserveHeaderSpace = true,
}: ShareChatLayoutProps) {
  const {
    setHeaderActions,
    reserveHeaderSpace: reserveSlot,
    clearHeaderActions,
  } = useHeaderActions();
  const { reserveSpace } = useHeaderActionsValue();
  const [showShareModal, setShowShareModal] = useState(false);

  useEffect(() => {
    if (!reserveHeaderSpace) {
      return;
    }
    reserveSlot();
    return () => {
      clearHeaderActions();
    };
  }, [reserveHeaderSpace, reserveSlot, clearHeaderActions]);

  useEffect(() => {
    if (!chatSession) {
      setHeaderActions(null);
      return;
    }

    setHeaderActions(
      <Button
        rightIcon={SvgShare}
        transient={showShareModal}
        tertiary
        onClick={() => setShowShareModal(true)}
      >
        Share Chat
      </Button>
    );

    return () => {
      setHeaderActions(null);
    };
  }, [chatSession, showShareModal, setHeaderActions, reserveSpace]);

  return (
    <>
      {chatSession && showShareModal && (
        <ShareChatSessionModal
          chatSession={chatSession}
          onClose={() => setShowShareModal(false)}
        />
      )}
      {children}
    </>
  );
}
