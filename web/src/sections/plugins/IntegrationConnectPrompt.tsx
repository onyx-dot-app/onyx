"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import { usePathname, useSearchParams } from "@opal/navigation";
import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import { connectAction } from "@/lib/integrations/connect";
import { useAgentChatIntegrations } from "@/lib/integrations/hooks";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import IntegrationConnectModal from "@/sections/plugins/IntegrationConnectModal";
import { locationKey } from "@/app/app/services/submitLocation";
import { isIntegrationOnInChat } from "@/lib/integrations/chat";

interface IntegrationConnectPromptProps {
  agentId: number;
  toolConfiguration: Pick<
    ToolConfigurationHandle,
    "isIntegrationEnabled" | "ready"
  >;
  disabled?: boolean;
  onConnectionsClosed?: () => void;
}

function WarningKey({ className, ...props }: IconProps) {
  return (
    <SvgKey {...props} className={cn(className, "stroke-status-warning-05")} />
  );
}

function InfoKey({ className, ...props }: IconProps) {
  return (
    <SvgKey {...props} className={cn(className, "stroke-status-info-05")} />
  );
}

/**
 * The chat's connect prompt: the integrations of the agent that are on and
 * need the user's sign-in. Such an integration gives the model no
 * action until the user connects it.
 */
export default function IntegrationConnectPrompt({
  agentId,
  toolConfiguration,
  disabled = false,
  onConnectionsClosed,
}: IntegrationConnectPromptProps) {
  const t = useTranslations("plugins.chat.connectPrompt");
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const catalog = useAgentChatIntegrations(agentId);
  const { refresh } = catalog;
  const [openedIds, setOpenedIds] = useState<number[] | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const integrations = catalog.integrations.filter((integration) =>
    isIntegrationOnInChat(integration, toolConfiguration.isIntegrationEnabled)
  );
  const pending = integrations.filter(
    (integration) => connectAction(integration) !== null
  );
  const needsReconnect = pending.some(
    (integration) => integration.status.state === "needs_reconnect"
  );
  const returnPath = locationKey(pathname, searchParams.toString());

  return (
    <>
      {pending.length > 0 && toolConfiguration.ready && (
        <Section width="auto" height="auto" className="ms-1">
          <Button
            ref={triggerRef}
            icon={needsReconnect ? WarningKey : InfoKey}
            prominence="tertiary"
            responsiveHideText
            tooltip={openedIds ? undefined : t("tooltip")}
            aria-label={t("trigger.label", { count: pending.length })}
            aria-haspopup="dialog"
            disabled={disabled}
            onClick={() => {
              void refresh();
              // Let open popovers close on this click first.
              window.setTimeout(
                () =>
                  setOpenedIds(pending.map((integration) => integration.id)),
                0
              );
            }}
          >
            {t("trigger.label", { count: pending.length })}
          </Button>
        </Section>
      )}
      {openedIds && (
        <IntegrationConnectModal
          integrations={integrations.filter((integration) =>
            openedIds.includes(integration.id)
          )}
          returnPath={returnPath}
          onClose={() => setOpenedIds(null)}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (triggerRef.current) triggerRef.current.focus();
            else onConnectionsClosed?.();
          }}
        />
      )}
    </>
  );
}
