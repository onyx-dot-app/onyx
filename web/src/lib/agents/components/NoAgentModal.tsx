"use client";

import { useTranslations } from "next-intl";
import { Modal, Button, Text } from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export function NoAgentModal() {
  const t = useTranslations("agents.modals");
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgOnyxOctagon} title={t("noAgent.title")} />
        <Modal.Body gap={2}>
          <Text as="p" color="text-03">
            {t("noAgent.body.description")}
          </Text>
          {isAdmin ? (
            <Text as="p" color="text-03">
              {t("noAgent.admin.description")}
            </Text>
          ) : (
            <Text as="p" color="text-03">
              {t("noAgent.nonAdmin.description")}
            </Text>
          )}
        </Modal.Body>
        {isAdmin && (
          <Modal.Footer>
            <Button
              href={ADMIN_ROUTES.CHAT_PREFERENCES.path}
              prominence="secondary"
            >
              {t("noAgent.reenableDefaultChat.label")}
            </Button>
            <Button href={ADMIN_ROUTES.AGENTS.path}>
              {t("noAgent.configureAgent.label")}
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
