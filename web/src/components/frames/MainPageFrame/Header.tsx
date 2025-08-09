"use client";

import React, { useState } from "react";
import { UserDropdown } from "@/components/UserDropdown";
import { UserSettingsModal } from "@/app/chat/modal/UserSettingsModal";
import { useChatContext } from "@/components/context/ChatContext";
import { useUser } from "@/components/user/UserProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { useLlmManager } from "@/lib/hooks";

export function Header() {
  const [userSettingsOpen, setUserSettingsOpen] = useState(false);
  const { llmProviders, ccPairs } = useChatContext();
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();

  const llmManager = useLlmManager(llmProviders, undefined, undefined);

  const toggleUserSettings = () => {
    setUserSettingsOpen(!userSettingsOpen);
  };

  return (
    <>
      <div className="flex items-center justify-end gap-2 pr-[16px] pt-[16px] z-50">
        <UserDropdown
          hideUserDropdown={false}
          toggleUserSettings={toggleUserSettings}
        />
      </div>
      {userSettingsOpen && (
        <UserSettingsModal
          setPopup={setPopup}
          setCurrentLlm={(newLlm) => llmManager.updateCurrentLlm(newLlm)}
          defaultModel={user?.preferences.default_model!}
          llmProviders={llmProviders}
          ccPairs={ccPairs}
          federatedConnectors={federatedConnectors}
          refetchFederatedConnectors={refetchFederatedConnectors}
          onClose={() => setUserSettingsOpen(false)}
        />
      )}
      {popup}
    </>
  );
}
