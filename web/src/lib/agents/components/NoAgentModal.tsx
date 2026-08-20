"use client";

import { Modal, Button, Text } from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";

export function NoAgentModal() {
  const { isAdmin } = useUser();

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgOnyxOctagon} title="No Agent Available" />
        <Modal.Body gap={2}>
          <Text as="p" color="text-03">
            You currently have no agent configured.
          </Text>
          {isAdmin ? (
            <Text as="p" color="text-03">
              As an administrator, you can create a new agent by visiting the
              admin panel.
            </Text>
          ) : (
            <Text as="p" color="text-03">
              Please contact your administrator to configure an agent for you.
            </Text>
          )}
        </Modal.Body>
        {isAdmin && (
          <Modal.Footer>
            <Button href="/admin/agents" prominence="secondary">
              Go to Admin Panel
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
