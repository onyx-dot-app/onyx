import Button from "@/refresh-components/buttons/Button";
import React, { memo, useCallback } from "react";
import Text from "@/refresh-components/texts/Text";
import { SvgProps } from "@/icons";
import SvgArrowExchange from "@/icons/arrow-exchange";
import Truncated from "@/refresh-components/texts/Truncated";
import SvgServer from "@/icons/server";
import {
  useChatModal,
  ModalIds,
} from "@/refresh-components/contexts/ChatModalContext";
import LLMConnectionIcons from "@/refresh-components/onboarding/components/LLMConnectionIcons";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import SvgSettings from "@/icons/settings";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgCheckCircle from "@/icons/check-circle";
import { OnboardingActions, OnboardingState } from "../types";

type LLMProviderProps = {
  title: string;
  subtitle: string;
  icon?: React.FunctionComponent<SvgProps>;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  disabled?: boolean;
  isConnected?: boolean;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
};
const LLMProviderInner = ({
  title,
  subtitle,
  icon: Icon,
  llmDescriptor,
  disabled,
  isConnected,
  onboardingState,
  onboardingActions,
}: LLMProviderProps) => {
  const { toggleModal } = useChatModal();

  const handleConnectClick = useCallback(() => {
    const iconNode = Icon ? (
      <Icon className="w-6 h-6" />
    ) : (
      <SvgServer className="w-6 h-6 stroke-text-04" />
    );

    toggleModal(ModalIds.LLMConnectionModal, true, {
      icon: <LLMConnectionIcons icon={iconNode} />,
      title: "Set up " + title,
      llmDescriptor,
      isCustomProvider: !llmDescriptor,
      onboardingState,
      onboardingActions,
    });
  }, [
    Icon,
    llmDescriptor,
    title,
    toggleModal,
    onboardingState,
    onboardingActions,
  ]);

  return (
    <div className="flex justify-between h-full w-full p-1 rounded-12 border border-border-01 bg-background-neutral-01">
      <div className="flex gap-1 p-1 flex-1 min-w-0">
        <div className="h-full p-0.5">
          {Icon ? (
            <Icon className="w-4 h-4" />
          ) : (
            <SvgServer className="w-4 h-4 stroke-text-04" />
          )}
        </div>
        <div className="min-w-0">
          <Text text04 mainUiAction>
            {title}
          </Text>
          <Truncated text03 secondaryBody>
            {subtitle}
          </Truncated>
        </div>
      </div>
      {isConnected ? (
        <>
          <IconButton internal icon={SvgSettings} disabled={disabled} />
          <div className="h-full p-1">
            <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
          </div>
        </>
      ) : (
        <Button
          tertiary
          rightIcon={SvgArrowExchange}
          disabled={disabled}
          onClick={handleConnectClick}
        >
          Connect
        </Button>
      )}
    </div>
  );
};

const LLMProvider = memo(LLMProviderInner);
export default LLMProvider;
