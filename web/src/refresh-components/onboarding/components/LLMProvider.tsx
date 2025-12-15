import React, { memo, useCallback, useState } from "react";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import ConnectionProviderIcon from "@/refresh-components/ConnectionProviderIcon";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import IconButton from "@/refresh-components/buttons/IconButton";
import { OnboardingActions, OnboardingState } from "../types";
import { cn, noProp } from "@/lib/utils";
import { LLMConnectionModalProps } from "./LLMConnectionModal";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgServer,
  SvgSettings,
} from "@opal/icons";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

export interface LLMProviderProps {
  title: string;
  subtitle: string;
  providerName?: string;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  disabled?: boolean;
  isConnected?: boolean;
  onClick: (props: LLMConnectionModalProps) => void;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  onOpenModal?: () => void;
  modal: ModalCreationInterface;
}

function LLMProviderInner({
  title,
  subtitle,
  providerName,
  llmDescriptor,
  disabled,
  isConnected,
  onboardingState,
  onboardingActions,
  onClick,
  onOpenModal,
  modal,
}: LLMProviderProps) {
  const [isHovered, setIsHovered] = useState(false);

  const handleCardClick = useCallback(() => {
    if (isConnected) {
      // If connected, redirect to admin page
      window.location.href = "/admin/configuration/llm";
      return;
    }

    // If not connected, open the modal
    const iconNode = providerName ? (
      <ProviderIcon provider={providerName} size={24} />
    ) : (
      <SvgServer className="w-6 h-6 stroke-text-04" />
    );

    onClick({
      icon: <ConnectionProviderIcon icon={iconNode} />,
      title: "Set up " + title,
      llmDescriptor,
      isCustomProvider: !llmDescriptor,
      onboardingState,
      onboardingActions,
      modal,
    });
    if (onOpenModal) {
      onOpenModal();
    }
  }, [
    providerName,
    llmDescriptor,
    title,
    onboardingState,
    onboardingActions,
    isConnected,
    onClick,
    onOpenModal,
    modal,
  ]);

  const handleSettingsClick = useCallback(
    noProp(() => (window.location.href = "/admin/configuration/llm")),
    []
  );

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      onClick={handleCardClick}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          handleCardClick();
        }
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      aria-disabled={disabled}
      className={cn(
        "flex justify-between h-full w-full p-1 rounded-12 border border-border-01 bg-background-neutral-01 transition-colors text-left",
        !disabled && "hover:bg-background-neutral-02 cursor-pointer",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <div className="flex items-center gap-1 p-1 flex-1 min-w-0">
        <div className="flex items-start h-full pt-0.5">
          {providerName ? (
            <ProviderIcon provider={providerName} size={16} className="" />
          ) : (
            <SvgServer className="w-4 h-4 stroke-text-04" />
          )}
        </div>
        <div className="min-w-0 flex flex-col justify-center">
          <Text as="p" text04 mainUiAction>
            {title}
          </Text>
          <Truncated text03 secondaryBody>
            {subtitle}
          </Truncated>
        </div>
      </div>
      {isConnected ? (
        <div className="flex items-start gap-1 p-1">
          {isHovered && (
            <IconButton
              internal
              icon={SvgSettings}
              disabled={disabled}
              onClick={handleSettingsClick}
              className="hover:bg-transparent"
            />
          )}
          <div className="p-1">
            <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
          </div>
        </div>
      ) : (
        <div className="flex items-start p-1">
          <div className="flex items-center gap-0.5">
            <Text as="p" text03 secondaryAction>
              Connect
            </Text>
            <div className="p-0.5">
              <SvgArrowExchange className="w-4 h-4 stroke-text-03" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const LLMProvider = memo(LLMProviderInner);
export default LLMProvider;
