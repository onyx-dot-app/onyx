"use client";

import { Modal, Button, Text } from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export function NoAgentModal() {
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgOnyxOctagon} title="No Agent Available" />
        <Modal.Body gap={2}>
          <Text as="p" color="text-03">
            There are currently no configured agents available. The default chat
            has also been explicitly disabled.
          </Text>
          {isAdmin ? (
            <Text as="p" color="text-03">
              As an administrator, you can either create a new agent by visiting
              the admin panel, or you can enable the default chat again.
            </Text>
          ) : (
            <Text as="p" color="text-03">
              Please contact your administrator to configure an agent for you,
              or to re-enable the default chat.
            </Text>
          )}
        </Modal.Body>
        {isAdmin && (
          <Modal.Footer>
            <Button
              href={ADMIN_ROUTES.CHAT_PREFERENCES.path}
              prominence="secondary"
            >
              Re-enable Default Chat
            </Button>
            <Button href={ADMIN_ROUTES.AGENTS.path}>
              Configure a New Agent
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
