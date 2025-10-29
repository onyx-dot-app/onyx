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

type LLMProviderProps = {
  title: string;
  subtitle: string;
  icon?: React.FunctionComponent<SvgProps>;
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  disabled?: boolean;
};
const LLMProviderInner = ({
  title,
  subtitle,
  icon: Icon,
  llmDescriptor,
  disabled,
}: LLMProviderProps) => {
  const { toggleModal } = useChatModal();

  const handleConnectClick = useCallback(() => {
    if (!llmDescriptor) return;

    const iconNode = Icon ? (
      <Icon className="w-6 h-6" />
    ) : (
      <SvgServer className="w-6 h-6 stroke-text-04" />
    );

    toggleModal(ModalIds.LLMConnectionModal, true, {
      icon: <LLMConnectionIcons icon={iconNode} />,
      title,
      llmDescriptor,
    });
  }, [Icon, llmDescriptor, title, toggleModal]);

  return (
    <div className="flex justify-between h-full w-full p-spacing-inline rounded-12 border border-border-01 bg-background-neutral-01">
      <div className="flex gap-spacing-inline p-spacing-inline flex-1 min-w-0">
        <div className="h-full p-spacing-inline-mini">
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
      <Button
        tertiary
        rightIcon={SvgArrowExchange}
        disabled={disabled}
        onClick={handleConnectClick}
      >
        Connect
      </Button>
    </div>
  );
};

const LLMProvider = memo(LLMProviderInner);
export default LLMProvider;
