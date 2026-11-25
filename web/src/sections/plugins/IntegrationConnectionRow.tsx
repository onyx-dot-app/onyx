"use client";

import { useTranslations } from "next-intl";
import { ContentAction } from "@opal/layouts";
import { SvgCheckCircle, SvgPlug } from "@opal/icons";
import type { MemberIntegration } from "@/lib/integrations/types";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

interface IntegrationConnectionRowProps {
  integration: MemberIntegration;
  /** Where the OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
}

/** One integration and its Connect button; the caller's card pads it. */
export default function IntegrationConnectionRow({
  integration,
  returnPath,
}: IntegrationConnectionRowProps) {
  const stateCopy = useTranslations("integrations");
  const { state, reason } = integration.status;
  return (
    <ContentAction
      icon={state === "connected" ? SvgCheckCircle : SvgPlug}
      color={state === "connected" ? "success" : "default"}
      title={integration.name}
      description={
        state === "needs_reconnect" && reason
          ? reason
          : stateCopy("connectionState", { state })
      }
      padding={0}
      rightChildren={
        <IntegrationConnectButton
          integration={integration}
          returnPath={returnPath}
        />
      }
    />
  );
}
