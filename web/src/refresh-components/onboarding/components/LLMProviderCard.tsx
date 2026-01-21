import React, { memo, useCallback, useState } from "react";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgServer,
  SvgSettings,
} from "@opal/icons";
import { ProviderIcon } from "@/app/admin/configuration/llm/ProviderIcon";

export interface LLMProviderCardProps {
  title: string;
  subtitle: string;
  providerName?: string;
  disabled?: boolean;
  isConnected?: boolean;
  onClick: () => void;
}

function LLMProviderCardInner({
  title,
  subtitle,
  providerName,
  disabled,
  isConnected,
  onClick,
}: LLMProviderCardProps) {
  const [isHovered, setIsHovered] = useState(false);

  const handleCardClick = useCallback(() => {
    if (isConnected) {
      // If connected, redirect to admin page
      window.location.href = "/admin/configuration/llm";
      return;
    }

    // If not connected, call onClick to open the form
    onClick();
  }, [isConnected, onClick]);

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
      <div className="flex gap-1 p-1 flex-1 min-w-0">
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

const LLMProviderCard = memo(LLMProviderCardInner);
export default LLMProviderCard;
