"use client";

import type { ComponentProps } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Modal, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import type { MemberIntegration } from "@/lib/integrations/types";
import IntegrationConnectionRow from "@/sections/plugins/IntegrationConnectionRow";

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
            {integrations.map((integration) => (
              <Card key={integration.id} padding={1} border="solid">
                <IntegrationConnectionRow
                  integration={integration}
                  returnPath={returnPath}
                />
              </Card>
            ))}
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
