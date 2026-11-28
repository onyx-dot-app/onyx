"use client";

import type { ComponentProps } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Modal, Text } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import { SvgCheckCircle, SvgKey, SvgPlug } from "@opal/icons";
import type { MemberIntegration } from "@/lib/integrations/types";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

interface IntegrationConnectModalProps {
  integrations: readonly MemberIntegration[];
  /** Where an OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
  onClose: () => void;
  onCloseAutoFocus?: ComponentProps<typeof Modal.Content>["onCloseAutoFocus"];
}

export default function IntegrationConnectModal({
  integrations,
  returnPath,
  onClose,
  onCloseAutoFocus,
}: IntegrationConnectModalProps) {
  const t = useTranslations("plugins.chat.connectPrompt");
  const stateCopy = useTranslations("integrations");
  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content
        width="sm"
        preventAccidentalClose={false}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <Modal.Header
          icon={SvgKey}
          title={t("title")}
          description={t("description")}
          onClose={onClose}
        />
        <Modal.Body padding={4} gap={3} alignItems="stretch">
          <Section gap={2} alignItems="stretch" height="auto">
            {integrations.map((integration) => {
              const { state, reason } = integration.status;
              return (
                <Card key={integration.id} padding={3} border="solid">
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
                </Card>
              );
            })}
          </Section>
          <Text font="secondary-body" color="text-03">
            {t("hint")}
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("done.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
